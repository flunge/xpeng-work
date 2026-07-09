import json
from typing import Any, Dict, List, Tuple


class MultiVehicleAdaptor:
    """多车型渲染UCP Adaptor

    将机器学习平台配置的scenario_list、target_vehicle、custom_label
    组装为processor所需的record格式，再回传给机器学习平台传入processor。
    """

    def __init__(self, **args):
        """初始化Adaptor

        Args:
            args: 机器学习平台传入的配置参数，包含：
                - scenario_list: 场景列表，格式为 [{"openloop_scenario_id": xxx, "closeloop_scenario_id": yyy}, ...]
                - target_vehicle: 目标车型，如 "E28"
                - custom_label: 自定义标签
        """
        scenario_list_raw = args.get("scenario_list", "[]")
        self.scenario_list = json.loads(scenario_list_raw) if isinstance(scenario_list_raw, str) else scenario_list_raw
        self.target_vehicle = args.get("target_vehicle", "")
        self.cloudsim_job_id= args.get("job_id", "")

    def prepare(self) -> None:
        """Prepare the adapter"""
        pass

    def count(self) -> int:
        """Return the total number of records in the data source."""
        return len(self.scenario_list)

    def load_data_chunks(
        self,
        batch_index: int,
        total_batches: int,
        batch_size: int,
        request_process_num: int,
    ) -> List[Tuple[Any, int]]:
        """Return Data Chunks based on batch index.

        每个scenario作为一个独立的data_chunk，
        每个data_chunk将由一个远程任务处理。

        Returns:
            List of Tuple of data_chunk and size of the data_chunk.
        """
        start = batch_index * batch_size
        end = min(start + batch_size, len(self.scenario_list))

        chunks = []
        for i in range(start, end):
            scenario = self.scenario_list[i]
            scenario_id = scenario.get("openloop_scenario_id")
            data_record = {
                "openloop_scenario_id": scenario_id,
                "closeloop_scenario_id": scenario.get("closeloop_scenario_id"),
            }
            chunk = {scenario_id: data_record}
            chunks.append((chunk, 1))
        return chunks

    def add_custom_context(self, row: dict, context: dict) -> None:
        """Add extra contextual data for downstream processing.

        将target_vehicle、custom_label注入context，
        供pre_processor/gpu_processor/post_processor使用。
        row参数来自iterate_data_chunk yield的data_record。
        """
        context["target_vehicle"] = self.target_vehicle
        context["job_id"] = self.cloudsim_job_id
