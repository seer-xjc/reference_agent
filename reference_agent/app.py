import os
import gradio as gr
from pathlib import Path
import tempfile
from collections import Counter
from docx import Document
import fitz
from dotenv import load_dotenv
from zhipuai import ZhipuAI
from utils import (
    get_reference_titles,
    get_citation_markers,
    search_from_arxiv,
    get_arxiv_metadata_only,
    batch_verify_citations_lightweight,
    load_pdf,
    load_prompt
)
from difflib import SequenceMatcher
import time

# 加载环境变量
load_dotenv()

def clean_title_for_comparison(title):
    """清理标题用于比较，去除标点符号、转换为小写等"""
    import re
    cleaned = re.sub(r'[^\w\s]', ' ', title.lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def is_similar(title1, title2, threshold=0.8):
    """改进的相似性比较函数"""
    similarity1 = SequenceMatcher(None, title1.lower(), title2.lower()).ratio()
    
    clean_title1 = clean_title_for_comparison(title1)
    clean_title2 = clean_title_for_comparison(title2)
    similarity2 = SequenceMatcher(None, clean_title1, clean_title2).ratio()
    
    words1 = set(clean_title1.split())
    words2 = set(clean_title2.split())
    if len(words1) > 0 and len(words2) > 0:
        word_overlap = len(words1.intersection(words2)) / len(words1.union(words2))
    else:
        word_overlap = 0
    
    max_similarity = max(similarity1, similarity2, word_overlap)
    return max_similarity > threshold, max_similarity

def load_document(file_path):
    """支持加载word/pdf文档"""
    if file_path.endswith('.pdf'):
        with fitz.open(file_path) as doc:
            return "\n".join([page.get_text() for page in doc])
    else:
        return "\n".join([p.text for p in Document(file_path).paragraphs if p.text])

def verify_citations_and_analyze_with_logs(file_path, lightweight_mode, skip_download, pdf_verify):
    """主要的文献检查函数，整合所有功能，带实时日志"""
    
    # 存储结果的字典
    results = {
        'doc_content': '',
        'titles': [],
        'citations_info': {},
        'arxiv_found': [],
        'arxiv_not_found': [],
        'verification_results': []
    }
    
    log_messages = []
    
    def add_log(message):
        """添加日志消息"""
        log_messages.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        return "\n".join(log_messages)
    
    try:
        # 初始化日志
        yield add_log("🚀 开始文献检查分析..."), "", "", "", "", "分析中..."
        
        # 1. 加载文档
        add_log(f"📖 正在加载文档: {Path(file_path).name}")
        doc_content = load_document(file_path)
        results['doc_content'] = doc_content
        add_log(f"✅ 文档加载完成，共 {len(doc_content)} 个字符")
        yield add_log(""), "", "", "", "", "分析中..."
        
        # 2. 提取参考文献标题
        add_log("🔍 正在提取参考文献标题...")
        titles = get_reference_titles(doc_content)
        results['titles'] = titles
        add_log(f"📚 提取到 {len(titles)} 篇参考文献")
        yield add_log(""), "", "", "", "", "分析中..."
        
        # 3. 分析引文数量和引用情况
        add_log("📊 正在分析引文标记...")
        citations_to_text = get_citation_markers(doc_content)
        add_log(f"🔖 找到 {len(citations_to_text)} 个引用标记")
        
        citations = []
        for citation, citation_text in citations_to_text:
            citations.extend(citation)
        
        # 统计未被引用的文献
        missed_citations = list(set(range(1, len(titles)+1)) - set(citations))
        
        # 统计重复引用
        counter = Counter(citations)
        duplicate_citations = [citation for citation, count in counter.items() if count > 1]
        
        results['citations_info'] = {
            'total_references': len(titles),
            'total_citations': len(citations_to_text),
            'unique_citations': len(set(citations)),
            'missed_citations': missed_citations,
            'duplicate_citations': duplicate_citations,
            'citation_details': [(citation, count) for citation, count in counter.items() if count > 1]
        }
        
        # 日志输出统计结果
        add_log(f"📈 引文统计完成:")
        add_log(f"   - 总引用数: {len(set(citations))} 个")
        add_log(f"   - 未引用文献: {len(missed_citations)} 篇")
        add_log(f"   - 重复引用: {len(duplicate_citations)} 篇")
        
        # 输出引文分析结果
        citation_analysis = format_citation_analysis(results)
        yield add_log(""), citation_analysis, "", "", "", "分析中..."
        
        # 4. 在arXiv中搜索文献
        add_log("🌐 开始在arXiv中搜索文献...")
        arxiv_found = []
        arxiv_not_found = []
        
        for i, title in enumerate(titles):
            add_log(f"📄 处理文献 {i+1}/{len(titles)}: {title[:50]}{'...' if len(title) > 50 else ''}")
            yield add_log(""), citation_analysis, "", "", "", f"正在搜索文献 {i+1}/{len(titles)}..."
            
            try:
                add_log(f"🔍 在arXiv搜索: {title[:30]}...")
                search_results = list(search_from_arxiv(title))
                found_match = False
                
                if search_results:
                    add_log(f"   📚 找到 {len(search_results)} 个搜索结果")
                    
                    for j, result in enumerate(search_results):
                        add_log(f"   🔍 检查结果 {j+1}: {result.title[:40]}...")
                        is_match, similarity = is_similar(result.title, title)
                        add_log(f"      相似度: {similarity:.3f}")
                        
                        if is_match:
                            add_log(f"   ✅ 找到匹配! 相似度: {similarity:.3f}")
                            arxiv_found.append({
                                'index': i + 1,
                                'title': title,
                                'arxiv_title': result.title,
                                'similarity': similarity,
                                'authors': [str(author) for author in result.authors],
                                'abstract': result.summary[:200] + "..." if len(result.summary) > 200 else result.summary
                            })
                            found_match = True
                            break
                        else:
                            add_log(f"      ❌ 相似度不足 (阈值: 0.6)")
                
                if not found_match:
                    add_log(f"   ❌ 未找到匹配的文献")
                    arxiv_not_found.append({
                        'index': i + 1,
                        'title': title
                    })
                    
            except Exception as e:
                add_log(f"   ❌ 搜索出错: {str(e)[:50]}...")
                arxiv_not_found.append({
                    'index': i + 1,
                    'title': title,
                    'error': str(e)
                })
            
            # 每处理5篇文献更新一次界面
            if (i + 1) % 5 == 0 or i == len(titles) - 1:
                results['arxiv_found'] = arxiv_found
                results['arxiv_not_found'] = arxiv_not_found
                arxiv_found_text, arxiv_not_found_text = format_arxiv_analysis(results)
                yield add_log(""), citation_analysis, arxiv_found_text, arxiv_not_found_text, "", f"已处理 {i+1}/{len(titles)} 篇文献"
        
        results['arxiv_found'] = arxiv_found
        results['arxiv_not_found'] = arxiv_not_found
        
        add_log(f"📊 arXiv搜索完成:")
        add_log(f"   - 找到匹配: {len(arxiv_found)} 篇")
        add_log(f"   - 未找到: {len(arxiv_not_found)} 篇")
        
        # 5. AI相关性验证（核心功能）
        add_log("🤖 开始AI相关性验证...")
        if lightweight_mode:
            add_log("   使用轻量级模式: arXiv元数据验证")
        else:
            add_log("   使用标准模式: PDF内容验证")
        
        yield add_log(""), citation_analysis, format_arxiv_analysis(results)[0], format_arxiv_analysis(results)[1], "", "正在进行AI验证..."
        
        add_log(f"   正在验证 {len(citations_to_text)} 个引用标记...")
        
        # 根据模式选择验证方法
        verification_results = []
        
        if lightweight_mode:
            # 轻量级模式：使用arXiv元数据
            for i, (citation, text) in enumerate(citations_to_text):
                add_log(f"   🔍 验证引用 {i+1}/{len(citations_to_text)}: {citation}")
                
                single_verification = batch_verify_citations_lightweight([(citation, text)], titles, "glm-4-flash")
                verification_results.extend(single_verification)
                
                if single_verification and single_verification[0]['status'] == 'verified':
                    result_text = single_verification[0].get('result', '')
                    if '<是>' in result_text:
                        add_log(f"      ✅ 验证通过")
                    elif '否' in result_text:
                        reason = result_text.replace('<否:', '').replace('>', '').strip()
                        add_log(f"      ❌ 需要检查: {reason[:50]}...")
                    else:
                        add_log(f"      ⚠️  结果不明确")
                else:
                    add_log(f"      ⏭️  跳过验证")
                
                # 每验证3个引用更新一次界面
                if (i + 1) % 3 == 0 or i == len(citations_to_text) - 1:
                    yield add_log(""), citation_analysis, format_arxiv_analysis(results)[0], format_arxiv_analysis(results)[1], "", f"已验证 {i+1}/{len(citations_to_text)} 个引用"
        else:
            # 标准模式：使用PDF内容验证
            ref_dir = Path("../data/references")
            ref_names = [int(file.stem) for file in ref_dir.iterdir() if file.is_file() and file.suffix == '.pdf']
            add_log(f"   📁 引用文件夹中找到 {len(ref_names)} 个PDF文件")
            
            for i, (citation, text) in enumerate(citations_to_text):
                add_log(f"   🔍 验证引用 {i+1}/{len(citations_to_text)}: {citation}")
                
                # 检查引用的文献是否都有对应的PDF文件
                missing_refs = set(citation) - set(ref_names)
                if missing_refs:
                    add_log(f"      ⏭️  跳过，PDF文件缺失: {sorted(missing_refs)}")
                    verification_results.append({
                        'citation': citation,
                        'status': 'skipped',
                        'reason': f'PDF文件缺失: {sorted(missing_refs)}'
                    })
                    continue
                
                try:
                    # 构建PDF文件路径并加载内容
                    reference_paths = [ref_dir / f"{index}.pdf" for index in citation]
                    add_log(f"      📖 加载PDF: {[f'{index}.pdf' for index in citation]}")
                    
                    references = load_pdf(reference_paths)
                    
                    if not references.strip():
                        add_log(f"      ⚠️  PDF内容为空，跳过")
                        verification_results.append({
                            'citation': citation,
                            'status': 'skipped',
                            'reason': 'PDF内容为空'
                        })
                        continue
                    
                    # 使用PDF内容进行验证
                    prompt_template = load_prompt("prompts/agent_prompt")
                    prompt = prompt_template.format(text, references)
                    
                    client = ZhipuAI(api_key=os.environ["ZHIPUAI_API_KEY"])
                    response = client.chat.completions.create(
                        model="glm-4-flash",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0
                    )
                    
                    result = response.choices[0].message.content
                    
                    verification_results.append({
                        'citation': citation,
                        'status': 'verified',
                        'result': result
                    })
                    
                    if '<是>' in result:
                        add_log(f"      ✅ 验证通过")
                    elif '否' in result:
                        reason = result.replace('<否:', '').replace('>', '').strip()
                        add_log(f"      ❌ 需要检查: {reason[:50]}...")
                    else:
                        add_log(f"      ⚠️  结果不明确: {result[:30]}...")
                        
                except Exception as e:
                    add_log(f"      ❌ 验证出错: {str(e)[:50]}...")
                    verification_results.append({
                        'citation': citation,
                        'status': 'error',
                        'reason': str(e)
                    })
                
                # 每验证3个引用更新一次界面
                if (i + 1) % 3 == 0 or i == len(citations_to_text) - 1:
                    yield add_log(""), citation_analysis, format_arxiv_analysis(results)[0], format_arxiv_analysis(results)[1], "", f"已验证 {i+1}/{len(citations_to_text)} 个引用"
        
        results['verification_results'] = verification_results
        
        # 统计验证结果
        verified_count = sum(1 for r in verification_results if r['status'] == 'verified')
        correct_count = sum(1 for r in verification_results if r['status'] == 'verified' and '<是>' in r.get('result', ''))
        incorrect_count = sum(1 for r in verification_results if r['status'] == 'verified' and '否' in r.get('result', ''))
        skipped_count = sum(1 for r in verification_results if r['status'] == 'skipped')
        error_count = sum(1 for r in verification_results if r['status'] == 'error')
        
        add_log(f"🎯 AI验证完成:")
        add_log(f"   - 已验证: {verified_count} 个引用")
        add_log(f"   - 查验无误: {correct_count} 个")
        add_log(f"   - 需要检查: {incorrect_count} 个")
        add_log(f"   - 跳过: {skipped_count} 个")
        add_log(f"   - 错误: {error_count} 个")
        
        if verified_count > 0:
            accuracy_rate = (correct_count / verified_count) * 100
            add_log(f"   - 准确率: {accuracy_rate:.1f}%")
        
        # 最终结果
        add_log("🎉 文献检查分析完成!")
        add_log("="*50)
        add_log("📋 分析总结:")
        add_log(f"   📚 参考文献: {len(titles)} 篇")
        add_log(f"   🔖 引用标记: {len(citations_to_text)} 个") 
        add_log(f"   ✅ arXiv找到: {len(arxiv_found)} 篇")
        add_log(f"   ❌ arXiv未找到: {len(arxiv_not_found)} 篇")
        add_log(f"   🤖 AI验证: {verified_count} 个引用")
        
        # 格式化最终结果
        citation_analysis = format_citation_analysis(results)
        arxiv_found_text, arxiv_not_found_text = format_arxiv_analysis(results)
        verified_correct, verified_incorrect = format_verification_results(results)
        
        yield add_log(""), citation_analysis, arxiv_found_text, arxiv_not_found_text, verified_correct, verified_incorrect, "✅ 分析完成！"
        
    except Exception as e:
        error_msg = f"❌ 错误: {str(e)}"
        add_log(error_msg)
        yield add_log(""), error_msg, "", "", "", error_msg

def format_citation_analysis(results):
    """格式化引文分析结果"""
    if 'error' in results:
        return f"❌ 错误: {results['error']}"
    
    info = results['citations_info']
    
    output = f"""📊 **引文分析结果**

**基本统计:**
- 参考文献总数：{info['total_references']} 篇
- 引用标记总数：{info['total_citations']} 个
- 不重复引用数：{info['unique_citations']} 个

**未被引用的文献：**"""
    
    if info['missed_citations']:
        output += f"\n⚠️ 共 {len(info['missed_citations'])} 篇文献未被引用："
        for citation in sorted(info['missed_citations']):
            output += f"\n   - 文献[{citation}]: {results['titles'][citation-1] if citation <= len(results['titles']) else '标题未知'}"
    else:
        output += "\n✅ 所有文献都被引用了"
    
    output += "\n\n**重复引用的文献：**"
    if info['duplicate_citations']:
        output += f"\n⚠️ 共 {len(info['duplicate_citations'])} 篇文献被重复引用："
        for citation, count in info['citation_details']:
            output += f"\n   - 文献[{citation}]：被引用 {count} 次"
    else:
        output += "\n✅ 没有重复引用的文献"
    
    return output

def format_arxiv_analysis(results):
    """格式化arXiv分析结果"""
    if 'error' in results:
        return f"❌ 错误: {results['error']}", f"❌ 错误: {results['error']}"
    
    found_output = "📚 **arXiv中可以找到的文献：**\n\n"
    if results['arxiv_found']:
        for item in results['arxiv_found']:
            found_output += f"**[{item['index']}]** {item['title']}\n"
            found_output += f"   - 匹配标题：{item['arxiv_title']}\n"
            found_output += f"   - 相似度：{item['similarity']:.3f}\n"
            found_output += f"   - 作者：{', '.join(item['authors'][:3])}{'...' if len(item['authors']) > 3 else ''}\n\n"
    else:
        found_output += "❌ 没有在arXiv中找到匹配的文献"
    
    not_found_output = "📚 **arXiv中不可以找到的文献：**\n\n"
    if results['arxiv_not_found']:
        for item in results['arxiv_not_found']:
            not_found_output += f"**[{item['index']}]** {item['title']}\n"
            if 'error' in item:
                not_found_output += f"   - 错误：{item['error']}\n"
            not_found_output += "\n"
    else:
        not_found_output += "✅ 所有文献都在arXiv中找到了"
    
    return found_output, not_found_output

def format_verification_results(results):
    """格式化验证结果"""
    if 'error' in results:
        return f"❌ 错误: {results['error']}", f"❌ 错误: {results['error']}"
    
    if not results.get('verification_results'):
        return "⚠️ 未进行相关性验证", "⚠️ 未进行相关性验证"
    
    verified_correct = []
    verified_incorrect = []
    
    for result in results['verification_results']:
        if result['status'] == 'verified':
            citation_str = str(result['citation'])
            if '<是>' in result.get('result', ''):
                verified_correct.append(citation_str)
            elif '否' in result.get('result', ''):
                ai_result = result.get('result', '')
                reason = ai_result.replace('<否:', '').replace('>', '').strip()
                
                # 获取文献标题
                citation_titles = []
                for cite_num in result['citation']:
                    if 1 <= cite_num <= len(results['titles']):
                        citation_titles.append(results['titles'][cite_num-1])
                
                verified_incorrect.append({
                    'citation': citation_str,
                    'titles': citation_titles,
                    'reason': reason
                })
    
    # 格式化查验无误的结果
    correct_output = "✅ **查验无误的文献：**\n\n"
    if verified_correct:
        correct_output += f"共 {len(verified_correct)} 个引用查验无误：\n"
        for citation in verified_correct:
            correct_output += f"- 引用 {citation}\n"
    else:
        correct_output += "⚠️ 没有查验无误的引用"
    
    # 格式化需要检查的结果
    incorrect_output = "⚠️ **相关性低，需重点检查的文献：**\n\n"
    if verified_incorrect:
        incorrect_output += f"共 {len(verified_incorrect)} 个引用需要重点检查：\n\n"
        for i, item in enumerate(verified_incorrect, 1):
            incorrect_output += f"**{i}. 引用 {item['citation']}**\n"
            if item['titles']:
                incorrect_output += f"   - 标题：{'; '.join(item['titles'])}\n"
            incorrect_output += f"   - 理由：{item['reason']}\n\n"
    else:
        incorrect_output += "✅ 所有验证的引用都相关性良好"
    
    return correct_output, incorrect_output

def process_document(file, lightweight, skip_download, pdf_verify):
    """处理上传的文档，带实时日志更新"""
    if file is None:
        yield "请先上传文档", "", "", "", "", "", ""
        return
    
    try:
        # 使用带日志的分析函数
        for result in verify_citations_and_analyze_with_logs(file.name, lightweight, skip_download, pdf_verify):
            if len(result) == 6:  # 中间结果
                logs, citation, arxiv_found, arxiv_not_found, verified_correct, status = result
                yield logs, citation, arxiv_found, arxiv_not_found, verified_correct, "", status
            elif len(result) == 7:  # 最终结果
                logs, citation, arxiv_found, arxiv_not_found, verified_correct, verified_incorrect, status = result
                yield logs, citation, arxiv_found, arxiv_not_found, verified_correct, verified_incorrect, status
        
    except Exception as e:
        error_msg = f"❌ 处理文档时发生错误: {str(e)}"
        yield f"[{time.strftime('%H:%M:%S')}] {error_msg}", error_msg, "", "", "", "", error_msg

# 创建Gradio界面
def create_interface():
    with gr.Blocks(
        title="文献引用检查工具",
        theme=gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="sky",
            neutral_hue="slate",
        )
    ) as demo:
        
        gr.Markdown("""
        # 📚 文献引用检查工具
        
        **功能简介：** 上传PDF或DOCX文档，自动检查文献引用的准确性和完整性
        
        **主要特性：**
        - ✅ 自动提取参考文献和引用标记
        - 🔍 在arXiv数据库中搜索匹配文献
        - 🤖 AI智能验证引用相关性
        - 📊 详细的统计分析报告
        """)
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📤 文档上传")
                file_input = gr.File(
                    label="选择PDF或DOCX文件",
                    file_types=[".pdf", ".docx"],
                    type="filepath"
                )
                
                gr.Markdown("### ⚙️ 检查选项")
                lightweight_mode = gr.Checkbox(
                    label="轻量级模式",
                    value=True,
                    info="使用arXiv元数据验证，更快速"
                )
                skip_download = gr.Checkbox(
                    label="跳过PDF下载",
                    value=True,
                    info="不下载PDF文件到本地"
                )
                pdf_verify = gr.Checkbox(
                    label="PDF验证",
                    value=False,
                    info="使用本地PDF进行深度验证"
                )
                
                process_btn = gr.Button(
                    "🚀 开始检查",
                    variant="primary",
                    size="lg"
                )
                
                status = gr.Textbox(
                    label="状态",
                    value="等待上传文档...",
                    interactive=False
                )
            
            with gr.Column(scale=1):
                gr.Markdown("### 📜 实时日志")
                logs = gr.Textbox(
                    label="处理日志",
                    lines=15,
                    max_lines=20,
                    interactive=False,
                    autoscroll=True,
                    placeholder="日志将在这里显示..."
                )
                
                clear_logs_btn = gr.Button(
                    "🗑️ 清除日志",
                    variant="secondary",
                    size="sm"
                )
        
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 📊 引文统计分析")
                citation_analysis = gr.Textbox(
                    label="引文数量分析",
                    lines=10,
                    interactive=False
                )
        
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 📚 arXiv文献检索结果")
                arxiv_found = gr.Textbox(
                    label="arXiv中可以找到的文献",
                    lines=8,
                    interactive=False
                )
            
            with gr.Column():
                arxiv_not_found = gr.Textbox(
                    label="arXiv中不可以找到的文献",
                    lines=8,
                    interactive=False
                )
        
        with gr.Row():
            with gr.Column():
                gr.Markdown("### ✅ 相关性验证结果")
                verified_correct = gr.Textbox(
                    label="查验无误",
                    lines=6,
                    interactive=False
                )
            
            with gr.Column():
                verified_incorrect = gr.Textbox(
                    label="相关性低，需重点检查",
                    lines=6,
                    interactive=False
                )
        
        # 事件绑定
        process_btn.click(
            fn=process_document,
            inputs=[file_input, lightweight_mode, skip_download, pdf_verify],
            outputs=[logs, citation_analysis, arxiv_found, arxiv_not_found, verified_correct, verified_incorrect, status]
        )
        
        # 清除日志事件
        clear_logs_btn.click(
            fn=lambda: "",
            outputs=logs
        )
        
        gr.Markdown("""
        ---
        **使用说明：**
        1. 上传PDF或DOCX格式的学术文档
        2. 选择合适的检查模式（推荐使用轻量级模式）
        3. 点击"开始检查"按钮进行分析
        4. 查看详细的分析结果和建议
        
        **注意事项：**
        - 需要设置ZHIPUAI_API_KEY环境变量
        - 轻量级模式速度更快，适合快速检查
        """)
    
    return demo

if __name__ == "__main__":
    # 检查API key
    if not os.environ.get("ZHIPUAI_API_KEY"):
        print("❌ 错误: 请设置ZHIPUAI_API_KEY环境变量")
        exit(1)
    
    # 启动界面
    demo = create_interface()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True
    )


