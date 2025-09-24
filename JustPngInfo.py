from PIL import Image

# 读取图片
img = Image.open('95259859.png')

# 获取所有元数据
print("所有元数据：")
print(img.info)

# 查看特定的参数（如果存在）
if 'parameters' in img.info:
    print("\nStable Diffusion 参数：")
    print(img.info['parameters'])