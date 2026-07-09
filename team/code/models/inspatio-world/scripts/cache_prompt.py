import argparse
import os
import sys
import torch

# Ensure repo root is on the path regardless of working directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

parser = argparse.ArgumentParser()
parser.add_argument("--prompt_txt", type=str, required=True,
                    help="Path to a plain-text file containing the prompt (first non-empty line is used)")
parser.add_argument("--output_path", type=str, default="./data/prompt_embeds.pt",)
parser.add_argument("--wan_model_folder", type=str,
                    default="/workspace/group_share/adc-sim/users/cloudsim/models/inspatio-world/checkpoints/Wan2.1-T2V-1.3B",
                    help="Folder containing T5 weights")
args = parser.parse_args()

with open(args.prompt_txt, "r") as f:
    lines = [l.strip() for l in f if l.strip()]
assert lines, f"No text found in {args.prompt_txt}"
prompt = lines[0]
print(f"Encoding prompt: {prompt!r}")

from utils.wan_wrapper import WanTextEncoder

encoder = WanTextEncoder(model_folder=args.wan_model_folder)
encoder.eval()

# Move to GPU if available
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
encoder.text_encoder.to(device)

with torch.no_grad():
    result = encoder(text_prompts=[prompt])

# result["prompt_embeds"]: [1, 512, 4096] bfloat16
os.makedirs(os.path.dirname(os.path.abspath(args.output_path)), exist_ok=True)
torch.save({"prompt_embeds": result["prompt_embeds"].cpu(), "prompt": prompt}, args.output_path)
print(f"Saved prompt embeddings to {args.output_path}  shape={result['prompt_embeds'].shape}")
