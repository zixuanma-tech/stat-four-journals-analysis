import tarfile
import os
import re
import pandas as pd  # 引入 pandas，方便最后导出表格

# ==========================================
# 模块一：特征提取函数 (引入了全部修复逻辑)
# ==========================================
def calculate_math_dimensions(tex_content):
    """
    计算 LaTeX 源码中“严格证明”与“公式展示”两个维度的字符占比。
    """
    # 1. 去噪：剔除 LaTeX 注释 (%)
    clean_tex = re.sub(r'%.*?$', '', tex_content, flags=re.MULTILINE)
    
    total_chars = len(clean_tex)
    if total_chars == 0:
        return {
            "total_valid_chars": 0, 
            "proof_chars": 0, "proof_density": 0.0, 
            "display_chars": 0, "display_density": 0.0
        }

    # 2. 提取维度一（严格证明）
    proof_envs = r'(proof|theorem|lemma|corollary|proposition)'
    proof_pattern = rf'\\begin\{{{proof_envs}\*?\}}(.*?)\\end\{{\1\*?\}}'
    proof_matches = re.findall(proof_pattern, clean_tex, flags=re.DOTALL)
    proof_chars = sum(len(match[1]) for match in proof_matches)

    # 3. 提取维度二（公式与设定展示）
    # (a) 八股文环境
    display_envs = r'(equation|align|eqnarray|assumption|condition)'
    env_pattern = rf'\\begin\{{{display_envs}\*?\}}(.*?)\\end\{{\1\*?\}}'
    env_matches = re.findall(env_pattern, clean_tex, flags=re.DOTALL)
    env_chars = sum(len(match[1]) for match in env_matches)
    
    # (b) 双美元符号独立公式 $$ ... $$
    dollar_pattern = r'\$\$(.*?)\$\$'
    dollar_matches = re.findall(dollar_pattern, clean_tex, flags=re.DOTALL)
    dollar_chars = sum(len(match) for match in dollar_matches)
    
    # (c) 斜杠方括号独立公式 \[ ... \]
    bracket_pattern = r'\\\[(.*?)\\\]'
    bracket_matches = re.findall(bracket_pattern, clean_tex, flags=re.DOTALL)
    bracket_chars = sum(len(match) for match in bracket_matches)

    total_display_chars = env_chars + dollar_chars + bracket_chars

    return {
        "total_valid_chars": total_chars,
        "proof_chars": proof_chars,
        "proof_density": round(proof_chars / total_chars, 4),
        "display_chars": total_display_chars,
        "display_density": round(total_display_chars / total_chars, 4)
    }

# ==========================================
# 模块二：压缩包读取函数
# ==========================================
def merge_tex_from_tar(tar_path):
    """
    直接从 tar.gz 压缩包中读取并合并所有 .tex 文件的内容。
    无需解压到本地硬盘！
    """
    merged_content = ""
    try:
        with tarfile.open(tar_path, "r:*") as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.endswith(".tex") and not member.name.split('/')[-1].startswith('._'):
                    f = tar.extractfile(member)
                    if f is not None:
                        text = f.read().decode('utf-8', errors='ignore')
                        merged_content += "\n" + text 
        return merged_content
    except Exception as e:
        print(f"[x] 解析 {tar_path} 时出错: {e}")
        return ""

# ==========================================
# 主程序：遍历、处理并导出表格
# ==========================================
if __name__ == "__main__":
    # 配置路径
    SOURCE_DIR = r"C:\Users\34098\WPSDrive\1732268580\WPS企业云盘\清华大学\我的企业文档\统计四大latex源码"
    OUTPUT_CSV = "latex_features_results.csv" # 结果保存的文件名
    
    print("开始批量清洗与特征提取任务...\n")
    
    # 用于存储每篇文章分析结果的列表
    results_list = []
    success_count = 0
    
    # 遍历文件夹
    for filename in os.listdir(SOURCE_DIR):
        if filename.endswith(".tar.gz"):
            # 提取 paperid (比如把 "AOS_2026_001.tar.gz" 变成 "AOS_2026_001")
            paperid = filename.replace(".tar.gz", "")
            file_path = os.path.join(SOURCE_DIR, filename)
            
            # 1. 内存中读取合并源码
            content = merge_tex_from_tar(file_path)
            
            if len(content) > 0:
                # 2. 执行正则特征提取
                stats = calculate_math_dimensions(content)
                
                # 3. 将 paperid 加入到这本字典里，并存入列表
                stats['paper_id'] = paperid
                results_list.append(stats)
                
                print(f"[+] 处理成功: {paperid} | 证明占比: {stats['proof_density']:.2%} | 公式展示占比: {stats['display_density']:.2%}")
                success_count += 1
            else:
                print(f"[-] 跳过: {paperid} (未找到有效的 .tex 内容)")

    print(f"\n==============================")
    print(f"处理完毕！共成功提取 {success_count} 篇文章的特征。")
    
    # 4. 将结果转换为 DataFrame 并保存为 CSV
    if results_list:
        df_results = pd.DataFrame(results_list)
        # 调整列的顺序，把 paper_id 放在第一列好看一些
        cols = ['paper_id', 'total_valid_chars', 'proof_chars', 'proof_density', 'display_chars', 'display_density']
        df_results = df_results[cols]
        
        df_results.to_csv(OUTPUT_CSV, index=False)
        print(f"特征数据已成功保存至: {OUTPUT_CSV}")