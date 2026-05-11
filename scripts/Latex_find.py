import pandas as pd
import requests
import time
import os
import urllib.parse
import xml.etree.ElementTree as ET
import re

# 1. 基础配置
CSV_FILE_PATH = 'aos_2026_metadata.csv'  # 你的表格文件名
OUTPUT_DIR = 'C:\\Users\\34098\\WPSDrive\\1732268580\\WPS企业云盘\\清华大学\\我的企业文档\\统计四大latex源码'          

ARXIV_API_URL = 'http://export.arxiv.org/api/query'

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def clean_title(title):
    cleaned = re.sub(r'[\"\':\(\)\[\]\{\}]', '', str(title))
    # 将多个连续空格合并为一个
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def fetch_arxiv_source(title, paper_id):
    """根据标题搜索并下载源码包，用 paperid 命名"""
    safe_title = clean_title(title)
    query = f'all:"{safe_title}"'
    encoded_query = urllib.parse.quote(query, safe='+:')
    
    request_url = f'{ARXIV_API_URL}?search_query={encoded_query}&max_results=1'
    
    try:
        response = requests.get(request_url, timeout=10)
        response.raise_for_status() 
        
        root = ET.fromstring(response.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        entry = root.find('atom:entry', ns)
        if entry is None:
            print(f"[-] arXiv 上未找到预印本: {title[:30]}...")
            return False 
            
        id_element = entry.find('atom:id', ns).text
        arxiv_id = id_element.split('/abs/')[-1]
        
        eprint_url = f'https://arxiv.org/e-print/{arxiv_id}'
        print(f"[+] 找到预印本 ID: {arxiv_id}，正在下载源码...")
        
        # 【关键修改】直接使用 paperid 作为文件名
        file_path = os.path.join(OUTPUT_DIR, f'{paper_id}.tar.gz')
        
        tar_response = requests.get(eprint_url, timeout=20)
        
        with open(file_path, 'wb') as f:
            f.write(tar_response.content)
            
        print(f"    --> 成功保存: {file_path}")
        return True
        
    except Exception as e:
        print(f"[x] 处理文章时出错: {title[:30]}... 错误信息: {e}")
        return False

# 2. 读取表格并执行
print("开始读取元数据表格...")
df = pd.read_csv(CSV_FILE_PATH)

if 'has_source_code' not in df.columns:
    df['has_source_code'] = 0

for index, row in df.head(40).iterrows():
    title = row['title'] 
    
    # 【关键修改】获取表格中的 paperid (请确保列名与你的 CSV 完全一致)
    paper_id = row['paper_id']     
    
    # 执行下载并传入 paperid
    success = fetch_arxiv_source(title, paper_id)
    
    if success:
        df.at[index, 'has_source_code'] = 1
        
    # 严格限速
    time.sleep(3)

# 3. 保存结果
updated_csv_path = 'aos_2026_metadata_updated.csv'
df.head(40).to_csv(updated_csv_path, index=False)
print(f"流程结束！结果已更新至: {updated_csv_path}")