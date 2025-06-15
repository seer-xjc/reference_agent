import os
from pathlib import Path
import argparse
from collections import Counter
from docx import Document
from dotenv import load_dotenv
from zhipuai import ZhipuAI
import fitz
import re
import logging
from utils import (
    load_prompt,
    normalize_doc,
    get_reference_titles,
    get_citation_markers,
    load_pdf,
    search_from_arxiv,
    batch_verify_citations_lightweight
)
from difflib import SequenceMatcher
import time

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def safe_download(result, title, i, max_retries=3):
    for attempt in range(max_retries):
        try:
            print(f"尝试下载: {title} (第 {attempt+1} 次)")
            result.download_pdf(dirpath="../data/references", filename=f"{i+1}.pdf")
            print(f"✅ 下载成功: {title}")
            return True
        except Exception as e:
            print(f"❌ 下载失败: {title}，错误: {e}")
            time.sleep(2)  # 简单退避
    print(f"🚫 放弃下载: {title}")
    return False  # 明确表示失败


def clean_title_for_comparison(title):
    """清理标题用于比较，去除标点符号、转换为小写等"""
    # 去除常见的标点符号和特殊字符
    cleaned = re.sub(r'[^\w\s]', ' ', title.lower())
    # 去除多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def is_similar(title1, title2, threshold=0.8):
    """改进的相似性比较函数"""
    # 原始标题比较
    similarity1 = SequenceMatcher(None, title1.lower(), title2.lower()).ratio()
    
    # 清理后的标题比较
    clean_title1 = clean_title_for_comparison(title1)
    clean_title2 = clean_title_for_comparison(title2)
    similarity2 = SequenceMatcher(None, clean_title1, clean_title2).ratio()
    
    # 关键词匹配
    words1 = set(clean_title1.split())
    words2 = set(clean_title2.split())
    if len(words1) > 0 and len(words2) > 0:
        word_overlap = len(words1.intersection(words2)) / len(words1.union(words2))
    else:
        word_overlap = 0
    
    # 综合评分（取最高分）
    max_similarity = max(similarity1, similarity2, word_overlap)
    
    print(f"    📊 相似度分析:")
    print(f"       原始: {similarity1:.3f}")
    print(f"       清理: {similarity2:.3f}")
    print(f"       词汇: {word_overlap:.3f}")
    print(f"       最终: {max_similarity:.3f} (阈值: {threshold})")
    
    return max_similarity > threshold


class Agent:
    def __init__(self, model, prompt, doc, ref):
        self.model = model
        self.prompt = load_prompt(prompt)
        self.doc = self._load_document(doc)  # 修改为统一加载方法
        self.ref = ref

    def _load_document(self, doc_path):
        """支持加载word/pdf文档"""
        if doc_path.endswith('.pdf'):
            with fitz.open(doc_path) as doc:
                return "\n".join([page.get_text() for page in doc])
        else:
            return "\n".join([p.text for p in Document(doc_path).paragraphs if p.text])

    def call_model(self, model, prompt):
        client = ZhipuAI(api_key=os.environ.get("ZHIPUAI_API_KEY"))
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            stream=False
        )
        return response.choices[0].message.content

    def verify_citations_referenced(self):
        print("第1步: 核查引文数量及引用情况")
        titles = get_reference_titles(self.doc)
        print(f"文献列表共有{len(titles)}篇参考文献")

        citations = []
        citations_to_text = get_citation_markers(self.doc)
        print(f"提取到{len(citations_to_text)}个引用标记")
        
        for i, (citation, citation_text) in enumerate(citations_to_text):
            print(f"引用标记 {i+1}: {citation} -> {citation_text[:50]}...")
            citations.extend(citation)

        print(f"总共找到{len(citations)}个引用编号: {sorted(set(citations))}")
        
        missed_citations = list(set(range(1, len(titles)+1)) - set(citations))
        if missed_citations:
            print(f"以下{len(missed_citations)}个文献没有被引用:")
            for citation in sorted(missed_citations):
                print(f"文献[{citation}]没有被引用")
        else:
            print("所有文献都被引用了 ✅")

        counter = Counter(citations)
        duplicate_count = 0
        for citation, count in counter.items():
            if count > 1:
                duplicate_count += 1
                print(f"文献[{citation}]的引用超过1次,共引用了{count}次")
        
        if duplicate_count == 0:
            print("没有重复引用的文献 ✅")

    def download_literatures(self):
        print("第2步: 开始下载文献:")
        titles = get_reference_titles(self.doc)
        failed_titles = []
        skipped_titles = []
        
        # 确保下载目录存在
        download_dir = Path("../data/references")
        download_dir.mkdir(parents=True, exist_ok=True)

        for i, title in enumerate(titles):
            pdf_filename = f"{i+1}.pdf"
            pdf_path = download_dir / pdf_filename
            
            print(f"\n📄 处理文献 {i+1}/{len(titles)}: {title}")
            
            # 检查文件是否已经存在
            if pdf_path.exists():
                print(f"⏭️  跳过已存在的文献 (文件: {pdf_filename})")
                skipped_titles.append(title)
                continue
            
            found = False
            print(f"🔍 在arXiv搜索: {title}")
            
            try:
                search_results = list(search_from_arxiv(title))
                print(f"   📚 找到 {len(search_results)} 个搜索结果")
                
                if not search_results:
                    print(f"❌ arXiv上无搜索结果")
                    failed_titles.append(title)
                    continue
                
                # 遍历搜索结果寻找最佳匹配
                best_match = None
                best_similarity = 0
                
                for j, result in enumerate(search_results):
                    print(f"   🔍 检查结果 {j+1}: {result.title}")
                    
                    if is_similar(result.title, title):
                        found = True
                        print(f"   ✅ 找到匹配!")
                        success = safe_download(result, title, i)
                        if success:
                            break
                        else:
                            found = False
                            
                if not found:
                    print(f"❌ 未找到足够相似的文献")
                    failed_titles.append(title)
                    
            except Exception as e:
                print(f"❌ 搜索过程出错: {str(e)}")
                failed_titles.append(title)

        print("\n" + "="*60)
        print("📊 下载统计:")
        
        # 统计结果
        total_titles = len(titles)
        skipped_count = len(skipped_titles)
        failed_count = len(failed_titles)
        success_count = total_titles - skipped_count - failed_count
        
        print(f"   📚 总文献数: {total_titles}")
        print(f"   ⏭️  已存在(跳过): {skipped_count}")
        print(f"   ✅ 新下载成功: {success_count}")
        print(f"   ❌ 下载失败: {failed_count}")
        
        if skipped_count > 0:
            print(f"\n⏭️  跳过的文献:")
            for i, title in enumerate(skipped_titles, 1):
                print(f"   {i}. {title}")
        
        if failed_count > 0:
            print(f"\n❌ 下载失败的文献:")
            for i, title in enumerate(failed_titles, 1):
                print(f"   {i}. {title}")
        
        if failed_count == 0:
            if success_count > 0:
                print(f"\n🎉 新下载的 {success_count} 篇文献全部成功!")
            if skipped_count + success_count == total_titles:
                print("🎉 所有文献都已准备就绪!")
        
        print("="*60)

    def verify_citation_sentences(self):
        print("第3步: 核查引文与文献的对应关系")
        bad_count = 0
        checked_count = 0
        skipped_count = 0
        
        ref_dir = Path(self.ref)
        ref_names = [int(file.stem) for file in ref_dir.iterdir() if file.is_file() and file.suffix == '.pdf']
        print(f"📁 引用文件夹中找到{len(ref_names)}个PDF文件: {sorted(ref_names)}")
        
        citations_to_text = get_citation_markers(self.doc)
        print(f"🔍 开始核查{len(citations_to_text)}个引用标记...")
        
        for i, (citation, text) in enumerate(citations_to_text):
            print(f"\n核查引用 {i+1}/{len(citations_to_text)}: {citation}")
            
            # 检查引用的文献是否都有对应的PDF文件
            missing_refs = set(citation) - set(ref_names)
            if missing_refs:
                print(f"⏭️  跳过引文{citation}，因为以下文献的PDF文件缺失: {sorted(missing_refs)}")
                skipped_count += 1
                continue
            
            try:
                # 构建PDF文件路径
                reference_paths = [ref_dir / f"{index}.pdf" for index in citation]
                
                # 检查所有文件是否存在
                missing_files = [path for path in reference_paths if not path.exists()]
                if missing_files:
                    print(f"⏭️  跳过引文{citation}，因为文件不存在: {[f.name for f in missing_files]}")
                    skipped_count += 1
                    continue
                
                print(f"📖 加载PDF文件: {[f'{index}.pdf' for index in citation]}")
                references = load_pdf(reference_paths)
                
                if not references.strip():
                    print(f"⚠️  跳过引文{citation}，因为PDF内容为空")
                    skipped_count += 1
                    continue
                
                print(f"🤖 使用AI模型验证引文...")
                prompt = self.prompt.format(text, references)
                response = self.call_model(self.model, prompt)
                checked_count += 1
                
                if "<是>" == response:
                    print(f"✅ 引文{citation}核查无误")
                elif "否" in response:
                    bad_count += 1
                    print(f"❌ 引文{citation}检测错误: {response}")
                else:
                    print(f"⚠️  引文{citation}检测结果不明确: {response}")
                    
            except Exception as e:
                print(f"❌ 处理引文{citation}时发生错误: {str(e)}")
                skipped_count += 1
                continue
                
        print("\n" + "="*50)
        print("📊 核查统计结果:")
        print(f"   总引用标记数: {len(citations_to_text)}")
        print(f"   已核查: {checked_count}")
        print(f"   跳过: {skipped_count}")
        print(f"   检测为错误: {bad_count}")
        print(f"   检测为正确: {checked_count - bad_count}")
        
        if checked_count > 0:
            accuracy_rate = ((checked_count - bad_count) / checked_count) * 100
            print(f"   准确率: {accuracy_rate:.1f}%")
        
        if bad_count == 0 and checked_count > 0:
            print("\n🎉 所有核查的引文都是正确的!")
        elif bad_count > 0:
            print(f"\n⚠️  发现{bad_count}个可能存在问题的引文，请仔细检查")

    def verify_citation_sentences_lightweight(self):
        """轻量级核查引文与文献的对应关系 - 使用arXiv元数据而非PDF下载"""
        print("第3步(轻量版): 使用arXiv元数据验证引文")
        
        titles = get_reference_titles(self.doc)
        citations_to_text = get_citation_markers(self.doc)
        
        print(f"参考文献数量: {len(titles)}")
        print(f"引用标记数量: {len(citations_to_text)}")
        print("正在验证...")
        
        # 使用轻量级验证
        verification_results = batch_verify_citations_lightweight(citations_to_text, titles, self.model)
        
        # 统计结果
        verified_count = sum(1 for r in verification_results if r['status'] == 'verified')
        skipped_count = sum(1 for r in verification_results if r['status'] == 'skipped')
        error_count = sum(1 for r in verification_results if r['status'] == 'error')
        correct_count = sum(1 for r in verification_results if r['status'] == 'verified' and '<是>' in r.get('result', ''))
        incorrect_count = sum(1 for r in verification_results if r['status'] == 'verified' and '否' in r.get('result', ''))
        
        print(f"\n验证结果:")
        print(f"  已验证: {verified_count}")
        print(f"  正确: {correct_count}")
        print(f"  有问题: {incorrect_count}")
        print(f"  跳过: {skipped_count}")
        
        if verified_count > 0:
            accuracy_rate = (correct_count / verified_count) * 100
            print(f"  准确率: {accuracy_rate:.1f}%")
        
        # 显示有问题的引用
        if incorrect_count > 0:
            print(f"\n发现问题的引用:")
            problem_count = 0
            for result in verification_results:
                if result['status'] == 'verified' and '否' in result.get('result', ''):
                    problem_count += 1
                    if problem_count <= 5:  # 只显示前5个问题
                        citation = result['citation']
                        ai_result = result.get('result', '')
                        reason = ai_result.replace('<否:', '').replace('>', '').strip()
                        print(f"  引用{citation}: {reason[:80]}...")
                    
            if problem_count > 5:
                print(f"  ...还有{problem_count - 5}个问题")
        
        # 简化的优势说明
        if verified_count > 0:
            print(f"\n轻量级验证优势: 快速、节省空间、基于最新数据")
        
        return verification_results


if __name__ == "__main__":
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="glm-4-flash")
    parser.add_argument("--prompt", type=str, default="../reference_agent/prompts/agent_prompt")
    parser.add_argument("--doc", type=str, default="c:\\Users\\seer\\Desktop\\reference_agent\\data\\docs\\abb.pdf")
    parser.add_argument("--ref", type=str, default="../data/references")
    parser.add_argument("--lightweight", action="store_true", default=False, help="使用轻量级模式,跳过PDF下载,仅使用arXiv元数据验证")
    parser.add_argument("--skip-download", action="store_true", default=False, help="跳过PDF下载步骤")
    parser.add_argument("--skip-pdf-verify", action="store_true", default=False, help="跳过PDF验证步骤")
    args = parser.parse_args()

    agent = Agent(args.model, args.prompt, args.doc, args.ref)
    
    # 第1步：总是执行引文数量检查
    agent.verify_citations_referenced()
    print("------------分割线-------------")
    
    if args.lightweight:
        print("🚀 使用轻量级模式 - 跳过PDF下载，直接使用arXiv元数据验证")
        agent.verify_citation_sentences_lightweight()
    else:
        # 传统模式
        if not args.skip_download:
            agent.download_literatures()
            print("------------分割线-------------")
        
        if not args.skip_pdf_verify:
            agent.verify_citation_sentences()
            print("------------分割线-------------")
        
        # 额外执行轻量级验证作为对比
        print("🔄 附加执行轻量级验证以供对比:")
        agent.verify_citation_sentences_lightweight()






