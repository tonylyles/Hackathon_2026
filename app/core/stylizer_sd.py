# stylizer_sd.py — SD 生成大头贴（静态精修照，模式扩展）
# 体积大（数 GB 权重），按需安装 diffusers 后才会被调用；8GB 显存必须开 offload 三件套
import torch


class SDStylizer:
    def __init__(self, model_id, device="cuda"):
        from diffusers import AutoPipelineForImageToImage  # 延迟导入
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.pipe = AutoPipelineForImageToImage.from_pretrained(
            model_id, torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        ).to(self.device)
        # 8GB 显存三件套
        self.pipe.enable_attention_slicing()
        self.pipe.enable_vae_tiling()
        try:
            self.pipe.enable_model_cpu_offload()
        except Exception:
            pass

    @torch.inference_mode()
    def generate(self, person_pil, prompt, negative="", steps=4, guidance=0.0, strength=0.6, seed=-1):
        gen = torch.Generator(self.device).manual_seed(seed) if seed >= 0 else None
        return self.pipe(
            prompt=prompt, negative_prompt=negative or None,
            image=person_pil, strength=strength, num_inference_steps=steps,
            guidance_scale=guidance, generator=gen,
        ).images[0]
