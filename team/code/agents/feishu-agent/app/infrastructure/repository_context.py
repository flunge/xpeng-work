from __future__ import annotations

import re
import subprocess
from pathlib import Path


class RepositoryContextProvider:
    def __init__(self, repo_root: str, *, max_files: int = 8, max_file_chars: int = 6000) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.max_files = max_files
        self.max_file_chars = max_file_chars

    def collect(self, query: str) -> tuple[str, list[str]]:
        if not self.repo_root.exists():
            return f"仓库路径不存在：{self.repo_root}", []

        files = self._select_files(query)
        per_file_limit = self._per_file_limit(query)
        sections: list[str] = []
        used_paths: list[str] = []
        if self._is_repo_overview_query(query):
            sections.append(self._repo_tree_summary())
        for path in files[: self.max_files]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel_path = path.relative_to(self.repo_root).as_posix()
            used_paths.append(rel_path)
            sections.append(f"## 文件: {rel_path}\n```\n{text[:per_file_limit]}\n```")

        if not sections:
            return "未检索到与问题明显相关的仓库文件。", []
        return "\n\n".join(sections), used_paths

    def _select_files(self, query: str) -> list[Path]:
        if self._is_repo_overview_query(query):
            return self._overview_files()

        explicit_paths = self._extract_explicit_paths(query)
        selected: list[Path] = []
        for rel_path in explicit_paths:
            path = (self.repo_root / rel_path).resolve()
            if self._is_safe_file(path):
                selected.append(path)

        keywords = self._query_keywords(query)
        if keywords:
            selected.extend(self._grep_files(keywords))

        selected.extend(self._fallback_files())
        return self._dedupe(selected)

    def _extract_explicit_paths(self, query: str) -> list[str]:
        candidates = re.findall(r"[\w./@+-]+\.(?:py|yaml|yml|json|md|txt|bash|sh|toml|ini|cfg|ts|tsx|js|jsx)", query)
        return [candidate.lstrip("./") for candidate in candidates]

    def _query_keywords(self, query: str) -> list[str]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", query)
        stop_words = {
            "什么",
            "为什么",
            "怎么",
            "如何",
            "请问",
            "这个",
            "那个",
            "一下",
            "仓库",
            "代码",
            "文件",
            "总结",
            "介绍",
            "内容",
        }
        keywords = [word for word in words if word not in stop_words]
        return keywords[:8]

    def _grep_files(self, keywords: list[str]) -> list[Path]:
        pattern = "|".join(re.escape(keyword) for keyword in keywords)
        command = [
            "python",
            "-c",
            (
                "import pathlib,re,sys; "
                "root=pathlib.Path(sys.argv[1]); pat=re.compile(sys.argv[2], re.I); "
                "skip={'.git','__pycache__','.pytest_cache','node_modules','data'}; "
                "count=0; "
                "\nfor p in root.rglob('*'):"
                "\n    parts=set(p.parts)"
                "\n    if parts & skip or not p.is_file(): continue"
                "\n    if p.suffix.lower() not in {'.py','.yaml','.yml','.json','.md','.txt','.bash','.sh','.toml','.ini','.cfg'}: continue"
                "\n    try: text=p.read_text(encoding='utf-8', errors='replace')[:200000]"
                "\n    except Exception: continue"
                "\n    if pat.search(str(p.relative_to(root))) or pat.search(text):"
                "\n        print(p); count += 1"
                "\n        if count >= 30: break"
            ),
            str(self.repo_root),
            pattern,
        ]
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=12)
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        return [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip()]

    def _overview_files(self) -> list[Path]:
        candidates = [
            self.repo_root / "README.md",
            self.repo_root / "xpeng_data_process" / "configs" / "config_vision.yaml",
            self.repo_root / "agents" / "README.md",
            self.repo_root / ".cursor" / "skills" / "3dgs-feishu-rd-agent" / "SKILL.md",
            self.repo_root / ".cursor" / "skills" / "3dgs-preprocess-task" / "SKILL.md",
            self.repo_root / ".cursor" / "skills" / "3dgs-preprocess-rd-loop" / "SKILL.md",
            self.repo_root / "skills" / "3dgs-preprocess-task" / "SKILL.md",
        ]
        return [path for path in candidates if self._is_safe_file(path)]

    def _fallback_files(self) -> list[Path]:
        candidates = [
            self.repo_root / "README.md",
            self.repo_root / "agents" / "README.md",
            self.repo_root / "xpeng_data_process" / "configs" / "config_vision.yaml",
            self.repo_root / ".cursor" / "skills" / "3dgs-feishu-rd-agent" / "SKILL.md",
            self.repo_root / ".cursor" / "skills" / "3dgs-preprocess-task" / "SKILL.md",
            self.repo_root / ".cursor" / "skills" / "3dgs-preprocess-rd-loop" / "SKILL.md",
            self.repo_root / "skills" / "3dgs-preprocess-task" / "SKILL.md",
        ]
        return [path for path in candidates if self._is_safe_file(path)]

    def _is_repo_overview_query(self, query: str) -> bool:
        normalized = query.lower()
        overview_keywords = ("总结", "介绍", "概览", "overview", "summary")
        repo_keywords = ("仓库", "repo", "代码库", "3dgs")
        return any(keyword in normalized for keyword in overview_keywords) and any(
            keyword in normalized for keyword in repo_keywords
        )

    def _per_file_limit(self, query: str) -> int:
        if self._is_repo_overview_query(query):
            return min(self.max_file_chars, 2500)
        return self.max_file_chars

    def _repo_tree_summary(self) -> str:
        important_dirs = [
            "xpeng_data_process",
            "omnire_joint_trainning",
            "pipeline/fuyao",
            "pipeline/ucp",
            "hil",
            "models",
            "sim_interface",
            "libs",
            "tools",
            "agents",
            "skills",
        ]
        lines = ["## 仓库关键目录"]
        for dirname in important_dirs:
            path = self.repo_root / dirname
            if path.exists():
                lines.append(f"- {dirname}/")
        return "\n".join(lines)

    def _is_safe_file(self, path: Path) -> bool:
        try:
            path.relative_to(self.repo_root)
        except ValueError:
            return False
        if not path.is_file():
            return False
        if any(part in {".git", "__pycache__", "node_modules", ".pytest_cache"} for part in path.parts):
            return False
        try:
            return path.stat().st_size <= 2_000_000
        except OSError:
            return False

    def _dedupe(self, paths: list[Path]) -> list[Path]:
        seen: set[Path] = set()
        result: list[Path] = []
        for path in paths:
            resolved = path.resolve()
            if resolved in seen or not self._is_safe_file(resolved):
                continue
            seen.add(resolved)
            result.append(resolved)
        return result
