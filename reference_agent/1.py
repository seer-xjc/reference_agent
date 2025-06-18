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
        yield add_log("🚀 开始文献检查分析..."), "", "", "", "", "分析中..."
        add_log(f"📖 正在加载文档: {Path(file_path).name}")
        doc_content = load_document(file_path)
        results['doc_content'] = doc_content
        add_log(f"✅ 文档加载完成，共 {len(doc_content)} 个字符")
        yield add_log(""), "", "", "", "", "分析中..."

        add_log("🔍 正在提取参考文献标题...")
        titles = get_reference_titles(doc_content)
        results['titles'] = titles
        add_log(f"📚 提取到 {len(titles)} 篇参考文献")
        yield add_log(""), "", "", "", "", "分析中..."

        add_log("📊 正在分析引文标记...")
        citations_to_text = get_citation_markers(doc_content)
        add_log(f"🔖 找到 {len(citations_to_text)} 个引用标记")

        citations = []
        for citation, citation_text in citations_to_text:
            citations.extend(citation)

        missed_citations = list(set(range(1, len(titles) + 1)) - set(citations))
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

        add_log(f"📈 引文统计完成:")
        add_log(f"   - 总引用数: {len(set(citations))} 个")
        add_log(f"   - 未引用文献: {len(missed_citations)} 篇")
        add_log(f"   - 重复引用: {len(duplicate_citations)} 篇")

        citation_analysis = format_citation_analysis(results)
        yield add_log(""), citation_analysis, "", "", "", "分析中..."

        add_log("🌐 开始在arXiv中搜索文献...")
        arxiv_found = []
        arxiv_not_found = []

        for i, title in enumerate(titles):
            add_log(f"📄 处理文献 {i + 1}/{len(titles)}: {title[:50]}{'...' if len(title) > 50 else ''}")
            yield add_log(""), citation_analysis, "", "", "", f"正在搜索文献 {i + 1}/{len(titles)}..."

            try:
                add_log(f"🔍 在arXiv搜索: {title[:30]}...")
                search_results = list(search_from_arxiv(title))
                found_match = False

                if search_results:
                    add_log(f"   📚 找到 {len(search_results)} 个搜索结果")
                    for j, result in enumerate(search_results):
                        add_log(f"   🔍 检查结果 {j + 1}: {result.title[:40]}...")
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
                                'abstract': result.summary[:200] + "..." if len(
                                    result.summary) > 200 else result.summary
                            })
                            found_match = True
                            break
                        else:
                            add_log(f"      ❌ 相似度不足 (阈值: 0.8)")

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

            if (i + 1) % 5 == 0 or i == len(titles) - 1:
                results['arxiv_found'] = arxiv_found
                results['arxiv_not_found'] = arxiv_not_found
                arxiv_found_text, arxiv_not_found_text = format_arxiv_analysis(results)
                yield add_log(
                    ""), citation_analysis, arxiv_found_text, arxiv_not_found_text, "", f"已处理 {i + 1}/{len(titles)} 篇文献"

        results['arxiv_found'] = arxiv_found
        results['arxiv_not_found'] = arxiv_not_found
        add_log(f"📊 arXiv搜索完成:")
        add_log(f"   - 找到匹配: {len(arxiv_found)} 篇")
        add_log(f"   - 未找到: {len(arxiv_not_found)} 篇")

        add_log("🤖 开始AI相关性验证...")
        if lightweight_mode:
            add_log("   使用轻量级模式: arXiv元数据验证")
        else:
            add_log("   使用标准模式: PDF内容验证")
        yield add_log(""), citation_analysis, format_arxiv_analysis(results)[0], format_arxiv_analysis(results)[
            1], "", "正在进行AI验证..."

        add_log(f"   正在验证 {len(citations_to_text)} 个引用标记...")
        verification_results = []

        if lightweight_mode:
            for i, (citation, text) in enumerate(citations_to_text):
                add_log(f"   🔍 验证引用 {i + 1}/{len(citations_to_text)}: {citation}")
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

                if (i + 1) % 3 == 0 or i == len(citations_to_text) - 1:
                    yield add_log(""), citation_analysis, format_arxiv_analysis(results)[0], \
                    format_arxiv_analysis(results)[1], "", f"已验证 {i + 1}/{len(citations_to_text)} 个引用"
        else:
            pass

        add_log("🎉 文献检查分析完成！")
        yield add_log(""), citation_analysis, format_arxiv_analysis(results)[0], format_arxiv_analysis(results)[
            1], "", "分析完成"

    except Exception as e:
        add_log(f"❌ 分析过程中发生错误: {str(e)[:50]}...")
        yield add_log(""), "", "", "", "", f"分析失败: {str(e)[:50]}..."


def format_citation_analysis(results):
    """格式化引文分析结果"""
    info = results['citations_info']
    output = []
    output.append("📊 引文分析结果：")
    output.append(f"- 总参考文献数: {info['total_references']}")
    output.append(f"- 总引用标记数: {info['total_citations']}")
    output.append(f"- 唯一引用编号数: {info['unique_citations']}")

    if info['missed_citations']:
        output.append(f"- 未被引用的文献: {len(info['missed_citations'])} 篇")
        for citation in sorted(info['missed_citations']):
            output.append(f"  - 文献[{citation}] 未被引用")
    else:
        output.append("- 所有文献均被引用 ✅")

    if info['duplicate_citations']:
        output.append(f"- 重复引用的文献: {len(info['duplicate_citations'])} 篇")
        for citation, count in info['citation_details']:
            output.append(f"  - 文献[{citation}] 被引用 {count} 次")
    else:
        output.append("- 无重复引用 ✅")

    return "\n".join(output)


def format_arxiv_analysis(results):
    """格式化arXiv搜索结果"""
    found_output = ["📚 arXiv找到的文献："]
    for item in results['arxiv_found']:
        found_output.append(f"- 文献[{item['index']}]: {item['title'][:50]}...")
        found_output.append(f"  - arXiv标题: {item['arxiv_title'][:50]}...")
        found_output.append(f"  - 相似度: {item['similarity']:.3f}")
        found_output.append(f"  - 作者: {', '.join(item['authors'][:3])}{'...' if len(item['authors']) > 3 else ''}")
        found_output.append(f"  - 摘要: {item['abstract'][:100]}...")

    not_found_output = ["❌ arXiv未找到的文献："]
    for item in results['arxiv_not_found']:
        not_found_output.append(f"- 文献[{item['index']}]: {item['title'][:50]}...")
        if 'error' in item:
            not_found_output.append(f"  - 错误: {item['error'][:50]}...")

    return "\n".join(found_output), "\n".join(not_found_output)


def submit_feedback(feedback):
    """处理用户反馈并保存到文件"""
    if not feedback.strip():
        return "⚠️ 反馈内容不能为空！"

    feedback_dir = Path("feedback")
    feedback_dir.mkdir(exist_ok=True)
    feedback_file = feedback_dir / "feedback.txt"

    try:
        with open(feedback_file, 'a', encoding='utf-8') as f:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] {feedback}\n")
        return "✅ 感谢您的反馈！已成功保存。"
    except Exception as e:
        return f"❌ 保存反馈失败: {str(e)[:50]}..."


with gr.Blocks() as demo:
    gr.Markdown("📚 文献引用查证智能体")
    with gr.Row():
        with gr.Column(scale=2):
            file_input = gr.File(label="上传PDF或DOCX文件", file_types=[".pdf", ".docx"])
            lightweight_checkbox = gr.Checkbox(label="轻量级模式 (使用arXiv元数据)", value=True)
            skip_download_checkbox = gr.Checkbox(label="跳过PDF下载", value=False)
            pdf_verify_checkbox = gr.Checkbox(label="跳过PDF内容验证", value=False)
            submit_button = gr.Button("开始检查", variant="primary")
        with gr.Column(scale=1):
            gr.Markdown("### 提供反馈")
            feedback_input = gr.Textbox(
                label="请留下您的反馈",
                lines=4,
                placeholder="请输入您对工具的建议或问题描述..."
            )
            feedback_submit_button = gr.Button("提交反馈", variant="secondary")
            feedback_result = gr.Textbox(label="反馈结果", interactive=False)

    log_output = gr.Textbox(label="运行日志", lines=10, interactive=False)
    citation_analysis_output = gr.Textbox(label="引文分析结果", lines=8, interactive=False)
    arxiv_found_output = gr.Textbox(label="arXiv找到的文献", lines=8, interactive=False)
    arxiv_not_found_output = gr.Textbox(label="arXiv未找到的文献", lines=8, interactive=False)
    status_output = gr.Textbox(label="状态", interactive=False)

    submit_button.click(
        verify_citations_and_analyze_with_logs,
        inputs=[file_input, lightweight_checkbox, skip_download_checkbox, pdf_verify_checkbox],
        outputs=[log_output, citation_analysis_output, arxiv_found_output, arxiv_not_found_output, status_output]
    )

    feedback_submit_button.click(
        submit_feedback,
        inputs=feedback_input,
        outputs=feedback_result
    )

demo.launch()