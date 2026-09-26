"""ComfyUI API-format graphs, mirroring the official image_qwen_image_2_1_t2i template.

UNETLoader -> QwenImage21Cache -> KSampler(euler/simple, cfg 1)
CLIPLoader(qwen_image) -> TextEncodeQwenImage21 -> KSampler -> VAEDecode -> PreviewImage
Optionally the Qwen3.5-9B prompt enhancer (TextGenerate) rewrites the prompt inside the same graph.
"""
from .config import Settings

IMAGE_NODE = "out_image"
ENHANCED_TEXT_NODE = "out_text"


def text_to_image(s: Settings, *, prompt: str, negative_prompt: str, width: int, height: int,
                  steps: int, cfg: float, seed: int, enhance: bool) -> dict:
    graph: dict = {
        "unet": {"class_type": "UNETLoader",
                 "inputs": {"unet_name": s.diffusion_model, "weight_dtype": "default"}},
        "cache": {"class_type": "QwenImage21Cache",
                  "inputs": {"model": ["unet", 0], "device": "auto", "dtype": "default"}},
        "clip": {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": s.text_encoder, "type": "qwen_image", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": s.vae}},
        "encode": {"class_type": "TextEncodeQwenImage21",
                   "inputs": {"clip": ["clip", 0], "prompt": prompt, "negative_prompt": negative_prompt,
                              "resolution": 1024}},
        "latent": {"class_type": "EmptyLatentImage",
                   "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sampler": {"class_type": "KSampler",
                    "inputs": {"model": ["cache", 0], "positive": ["encode", 0], "negative": ["encode", 1],
                               "latent_image": ["latent", 0], "seed": seed, "steps": steps, "cfg": cfg,
                               "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]}},
        # PreviewImage writes to ComfyUI's temp dir (wiped on restart), so outputs don't pile up.
        IMAGE_NODE: {"class_type": "PreviewImage", "inputs": {"images": ["decode", 0]}},
    }
    if enhance:
        graph["pe_clip"] = {"class_type": "CLIPLoader",
                            "inputs": {"clip_name": s.enhancer, "type": "stable_diffusion", "device": "default"}}
        graph["pe"] = {"class_type": "TextGenerate",
                       "inputs": {"clip": ["pe_clip", 0], "prompt": prompt, "max_length": 2048,
                                  "sampling_mode": "off", "thinking": False,
                                  "use_default_template": True, "mtp": "auto"}}
        graph[ENHANCED_TEXT_NODE] = {"class_type": "PreviewAny", "inputs": {"source": ["pe", 0]}}
        graph["encode"]["inputs"]["prompt"] = ["pe", 0]
    return graph
