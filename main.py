from PIL import Image
import json
from datetime import datetime

def parse_png_info(image_path):
    """解析 PNG 圖片的元數據並美化輸出"""
    try:
        img = Image.open(image_path)
        metadata = img.info
        
        print("="*80)
        print(f"🖼️  PNG 圖片資訊解析")
        print(f"📁 檔案路徑: {image_path}")
        print(f"📐 圖片尺寸: {img.size[0]} x {img.size[1]} 像素")
        print(f"🎨 顏色模式: {img.mode}")
        print(f"⏰ 解析時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        if not metadata:
            print("❌ 未找到元數據資訊")
            return
        
        # 檢查是否為 ComfyUI 生成的圖片
        if 'prompt' in metadata and 'workflow' in metadata:
            print("\n🔍 偵測到 ComfyUI 工作流")
            parse_comfyui_info(metadata)
        elif 'parameters' in metadata:
            print("\n🔍 偵測到 Stable Diffusion WebUI 參數")
            parse_webui_info(metadata)
        else:
            print("\n📋 通用元數據:")
            for key, value in metadata.items():
                print(f"   {key}: {value}")
                
    except Exception as e:
        print(f"❌ 解析出錯: {e}")

def parse_comfyui_info(metadata):
    """解析 ComfyUI 工作流資訊"""
    try:
        # 解析 prompt (節點資訊)
        prompt_data = json.loads(metadata['prompt'])
        
        print("\n🎯 生成參數:")
        
        # 查找 KSampler 節點
        ksampler_node = None
        for node_id, node_data in prompt_data.items():
            if node_data.get('class_type') == 'KSampler':
                ksampler_node = node_data
                break
        
        if ksampler_node:
            inputs = ksampler_node['inputs']
            print(f"   🌱 隨機種子: {inputs.get('seed', 'N/A')}")
            print(f"   🔢 採樣步數: {inputs.get('steps', 'N/A')}")
            print(f"   ⚖️  CFG Scale: {inputs.get('cfg', 'N/A')}")
            print(f"   🎲 採樣器: {inputs.get('sampler_name', 'N/A')}")
            print(f"   📅 排程器: {inputs.get('scheduler', 'N/A')}")
            print(f"   🔄 去噪強度: {inputs.get('denoise', 'N/A')}")
        
        # 查找模型資訊
        checkpoint_node = None
        for node_id, node_data in prompt_data.items():
            if node_data.get('class_type') == 'CheckpointLoaderSimple':
                checkpoint_node = node_data
                break
        
        if checkpoint_node:
            model_name = checkpoint_node['inputs'].get('ckpt_name', 'N/A')
            print(f"   🤖 模型: {model_name}")
        
        # 查找 LoRA 資訊
        lora_nodes = []
        for node_id, node_data in prompt_data.items():
            if node_data.get('class_type') == 'LoraLoader':
                lora_nodes.append(node_data)
        
        if lora_nodes:
            print(f"\n🎨 LoRA 模型:")
            for i, lora_node in enumerate(lora_nodes, 1):
                inputs = lora_node['inputs']
                lora_name = inputs.get('model', 'N/A')
                strength = inputs.get('strength', 'N/A')
                print(f"   {i}. {lora_name} (強度: {strength})")
        
        # 查找圖片尺寸
        latent_node = None
        for node_id, node_data in prompt_data.items():
            if node_data.get('class_type') == 'EmptyLatentImage':
                latent_node = node_data
                break
        
        if latent_node:
            inputs = latent_node['inputs']
            width = inputs.get('width', 'N/A')
            height = inputs.get('height', 'N/A')
            batch_size = inputs.get('batch_size', 'N/A')
            print(f"   📏 生成尺寸: {width} x {height}")
            print(f"   📦 批次大小: {batch_size}")
        
        # 查找正面提示詞
        positive_prompt = None
        for node_id, node_data in prompt_data.items():
            if node_data.get('class_type') == 'CLIPTextEncode':
                text = node_data['inputs'].get('text', '')
                if text.strip():  # 非空的提示詞
                    positive_prompt = text
                    break
        
        if positive_prompt:
            print(f"\n✨ 正面提示詞:")
            # 按句子分割，使輸出更整齊
            sentences = positive_prompt.replace('. ', '.\n   ').strip()
            print(f"   {sentences}")
        
        # 查找負面提示詞（通常是空的，但也檢查一下）
        for node_id, node_data in prompt_data.items():
            if node_data.get('class_type') == 'CLIPTextEncode':
                text = node_data['inputs'].get('text', '')
                if text.strip() and text != positive_prompt:
                    print(f"\n🚫 負面提示詞:")
                    print(f"   {text}")
                    break
        
        # 顯示工作流統計
        workflow_data = json.loads(metadata['workflow'])
        node_count = len(workflow_data.get('nodes', []))
        print(f"\n📊 工作流統計:")
        print(f"   🔗 節點數量: {node_count}")
        print(f"   🆔 工作流ID: {workflow_data.get('id', 'N/A')}")
        
        # 顯示前端版本
        frontend_version = workflow_data.get('extra', {}).get('frontendVersion', 'N/A')
        if frontend_version != 'N/A':
            print(f"   🖥️  ComfyUI 版本: {frontend_version}")
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析錯誤: {e}")
    except Exception as e:
        print(f"❌ ComfyUI 資訊解析錯誤: {e}")

def parse_webui_info(metadata):
    """解析 Stable Diffusion WebUI 參數"""
    try:
        params = metadata['parameters']
        lines = params.split('\n')
        
        # 提取主要資訊
        positive_prompt = ""
        negative_prompt = ""
        settings = {}
        
        in_negative = False
        for line in lines:
            line = line.strip()
            if line.startswith('Negative prompt:'):
                in_negative = True
                negative_prompt = line.replace('Negative prompt:', '').strip()
            elif line.startswith('Steps:'):
                # 解析設定行
                parts = line.split(', ')
                for part in parts:
                    if ':' in part:
                        key, value = part.split(':', 1)
                        settings[key.strip()] = value.strip()
                in_negative = False
            elif not in_negative and not line.startswith('Steps:'):
                if positive_prompt:
                    positive_prompt += " " + line
                else:
                    positive_prompt = line
            elif in_negative and not line.startswith('Steps:'):
                negative_prompt += " " + line
        
        print(f"\n✨ 正面提示詞:")
        print(f"   {positive_prompt}")
        
        if negative_prompt:
            print(f"\n🚫 負面提示詞:")
            print(f"   {negative_prompt}")
        
        print(f"\n🎯 生成參數:")
        setting_names = {
            'Steps': '🔢 採樣步數',
            'Sampler': '🎲 採樣器',
            'CFG scale': '⚖️  CFG Scale',
            'Seed': '🌱 隨機種子',
            'Size': '📏 尺寸',
            'Model hash': '🔑 模型雜湊',
            'Model': '🤖 模型',
            'Denoising strength': '🔄 去噪強度',
            'Clip skip': '⏭️  CLIP跳過',
        }
        
        for key, value in settings.items():
            display_name = setting_names.get(key, f"   {key}")
            print(f"   {display_name}: {value}")
            
    except Exception as e:
        print(f"❌ WebUI 參數解析錯誤: {e}")

# 使用示例
if __name__ == "__main__":
    # 替換為你的圖片路徑
    image_path = "95259859.png"  # 修改這裡為你的圖片路徑
    parse_png_info(image_path)
