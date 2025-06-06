import re
import os
import arxiv
import fitz
from ast import literal_eval
from zhipuai import ZhipuAI
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

def load_prompt(file):
    prompt = ""
    with open(file, 'r', encoding='utf-8') as f:
        for line in f:
            prompt += line
    return prompt

def normalize_doc(doc):
    paragraphs = [paragraph.text for paragraph in doc.paragraphs if paragraph.text]
    return paragraphs

def get_reference_titles(doc_content):
    """通用参考文献提取方法，支持word/pdf"""
    full_text = "\n".join(doc_content) if isinstance(doc_content, list) else doc_content
    return extract_references_with_ai(full_text)

def parse_citation_line(line):
    """解析单行引用标记，支持多种格式"""
    line = line.strip()
    if not line:
        return None
    
    try:
        # 尝试直接解析
        return literal_eval(line)
    except (SyntaxError, ValueError):
        # 如果直接解析失败，尝试修复常见格式问题
        try:
            # 处理缺少结束引号的情况
            if line.count('"') == 1:
                line = line + '"'
            # 处理缺少结束括号的情况
            if line.count('[') > line.count(']'):
                line = line + ']'
            # 处理缺少结束括号的情况
            if line.count('(') > line.count(')'):
                line = line + ')'
            return literal_eval(line)
        except (SyntaxError, ValueError):
            # 最后尝试正则表达式提取
            pattern = r'\[(\d+(?:,\s*\d+)*)\].*?"([^"]*)"?'
            match = re.search(pattern, line)
            if match:
                citation_str = match.group(1)
                text = match.group(2)
                citations = [int(x.strip()) for x in citation_str.split(',')]
                return [citations, text]
            else:
                logger.warning(f"无法解析的引用标记格式: {line}")
                return None

def extract_citations_with_regex(content):
    """使用正则表达式提取引用标记作为备用方法"""
    results = []
    
    # 多种引用标记模式
    patterns = [
        # 匹配 [1], [1,2], [1, 2, 3] 等格式
        r'\[(\d+(?:\s*,\s*\d+)*)\]',
        # 匹配可能有空格的情况
        r'\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]'
    ]
    
    all_citations = set()
    
    for pattern in patterns:
        matches = re.finditer(pattern, content)
        for match in matches:
            citation_str = match.group(1)
            # 解析引用编号
            citations = []
            for num_str in citation_str.split(','):
                try:
                    num = int(num_str.strip())
                    citations.append(num)
                    all_citations.add(num)
                except ValueError:
                    continue
            
            if citations:
                # 提取引用前后的上下文作为句子
                start = max(0, match.start() - 100)
                end = min(len(content), match.end() + 100)
                context = content[start:end].strip()
                
                # 尝试找到完整的句子
                sentences = re.split(r'[.!?]\s+', context)
                target_sentence = ""
                for sentence in sentences:
                    if match.group(0) in sentence:
                        target_sentence = sentence.strip()
                        break
                
                if not target_sentence:
                    target_sentence = context
                
                results.append([citations, target_sentence])
    
    # 去重并按引用编号排序
    unique_results = []
    seen_citations = set()
    
    for citations, text in results:
        citation_key = tuple(sorted(citations))
        if citation_key not in seen_citations:
            seen_citations.add(citation_key)
            unique_results.append([citations, text])
    
    unique_results.sort(key=lambda x: min(x[0]))
    
    logger.info(f"正则表达式方法提取到{len(unique_results)}个引用标记")
    logger.info(f"发现的所有引用编号: {sorted(all_citations)}")
    return unique_results

def get_citation_markers(content):
    """使用AI模型提取引用标记，并添加备用的正则表达式方法"""
    try:
        if not content:
            print("警告: 文档内容为空")
            return []
        
        # 首先使用正则表达式方法作为主要方法，因为它更可靠
        regex_results = extract_citations_with_regex(content)
        
        # 如果正则表达式找到了足够的结果，直接返回
        if len(regex_results) > 10:  # 假设正常文档应该有超过10个引用
            print(f"提取到{len(regex_results)}个引用标记")
            return regex_results
        
        # 否则尝试AI方法作为补充
        try:
            client = ZhipuAI(api_key=os.environ["ZHIPUAI_API_KEY"])
            
            # 由于内容可能很长，我们分段处理
            chunk_size = 8000  # 每段8000字符
            all_ai_results = []
            
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i+chunk_size]
                
                prompt = """请从以下文本中提取所有文献引用标记及对应段落：
1. 识别形如[1]或[1,2,3]或[1, 2, 3]的引用标记
2. 每个引用标记单独一行，格式：引用编号列表|对应段落文本
3. 例如：[1, 2, 3]|这是包含引用的段落文本

文本内容：
{content}"""

                response = client.chat.completions.create(
                    model="glm-4-flash",
                    messages=[{"role": "user", "content": prompt.format(content=chunk)}],
                    temperature=0
                )
                
                # 解析AI响应
                for line in response.choices[0].message.content.split('\n'):
                    if '|' in line and '[' in line:
                        try:
                            citation_part, text_part = line.split('|', 1)
                            citation_match = re.search(r'\[([^\]]+)\]', citation_part)
                            if citation_match:
                                citation_str = citation_match.group(1)
                                citations = [int(x.strip()) for x in citation_str.split(',')]
                                all_ai_results.append([citations, text_part.strip()])
                        except (ValueError, IndexError):
                            continue
            
            # 合并正则表达式和AI结果
            combined_results = regex_results[:]
            existing_citations = set()
            for result in regex_results:
                existing_citations.update(result[0])
            
            for result in all_ai_results:
                if not any(cite in existing_citations for cite in result[0]):
                    combined_results.append(result)
                    existing_citations.update(result[0])
            
            print(f"提取到{len(combined_results)}个引用标记")
            return combined_results
            
        except Exception as e:
            print(f"AI方法失败，使用正则表达式结果: {str(e)[:30]}...")
            return regex_results
        
    except Exception as e:
        print(f"引用标记提取失败: {str(e)[:30]}...")
        return []

def load_pdf(files):
    """加载PDF文件内容"""
    if not isinstance(files, list):
        logger.error("参数必须为list类型")
        raise TypeError("references参数应为list类型")
        
    text = []
    try:
        for file in files:
            with fitz.open(file) as pdf:
                text.extend(page.get_text() for page in pdf)
        return "\n".join(text)
    except Exception as e:
        logger.error(f"PDF加载失败: {str(e)}")
        raise

def search_from_arxiv(query):
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=5
    )
    return client.results(search)

def extract_references_with_ai(content, model="glm-4-flash"):
    """使用AI模型从文本内容中提取参考文献标题"""
    try:
        if not content:
            print("警告: 文档内容为空")
            return []
            
        client = ZhipuAI(api_key=os.environ["ZHIPUAI_API_KEY"])
        
        prompt = """请从以下文本中精确提取参考文献部分的论文标题列表：
1. 只返回参考文献章节中的论文标题  
2. 忽略作者、期刊、年份、序号等信息
3. 标题不要包含序号（如[1]、1.等）
4. 输出格式为纯文本，每行一个标题

示例输出：
Single image super-resolution using deep convolutional networks
Enhanced deep residual networks for single image super-resolution
Image super-resolution using very deep convolutional networks

文本内容：
{content}"""

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt.format(content=content)}],
            temperature=0
        )
        
        raw_titles = [title.strip() for title in response.choices[0].message.content.split('\n') if title.strip()]
        
        # 进一步清理标题，去除可能残留的序号
        clean_titles = []
        for title in raw_titles:
            # 使用正则表达式去除开头的序号
            cleaned_title = re.sub(r'^\[\d+\]\s*', '', title)  # 去除[1] 
            cleaned_title = re.sub(r'^\d+\.\s*', '', cleaned_title)  # 去除1. 
            cleaned_title = re.sub(r'^\(\d+\)\s*', '', cleaned_title)  # 去除(1) 
            cleaned_title = cleaned_title.strip()
            
            # 确保标题不为空且有意义
            if len(cleaned_title) > 10 and not cleaned_title.isdigit():
                clean_titles.append(cleaned_title)
        
        print(f"提取到{len(clean_titles)}篇参考文献标题")
        return clean_titles
        
    except KeyError:
        print("错误: ZHIPUAI_API_KEY环境变量未设置")
        raise
    except Exception as e:
        print(f"参考文献提取失败: {str(e)}")
        return []

def get_arxiv_metadata_only(query, max_results=5):
    """获取arXiv论文元数据而不下载PDF"""
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results
    )
    
    results = []
    for result in client.results(search):
        metadata = {
            'title': result.title,
            'authors': [str(author) for author in result.authors],
            'abstract': result.summary,
            'published': result.published,
            'updated': result.updated,
            'categories': result.categories,
            'arxiv_id': result.entry_id,
            'pdf_url': result.pdf_url,
            'doi': getattr(result, 'doi', None),
            'journal_ref': getattr(result, 'journal_ref', None)
        }
        results.append(metadata)
    
    return results

def verify_citation_with_metadata(citation_text, paper_metadata):
    """使用论文元数据验证引用，无需下载PDF"""
    # 构建用于验证的文本内容（标题+摘要）
    reference_content = f"""
标题: {paper_metadata['title']}
作者: {', '.join(paper_metadata['authors'])}
摘要: {paper_metadata['abstract']}
发表时间: {paper_metadata['published']}
分类: {', '.join(paper_metadata['categories'])}
"""
    
    return reference_content

def batch_verify_citations_lightweight(citations_to_text, titles, model="glm-4-flash"):
    """轻量级批量验证引用 - 使用元数据而非PDF"""
    client = ZhipuAI(api_key=os.environ["ZHIPUAI_API_KEY"])
    verification_results = []
    
    for citation, text in citations_to_text:
        # 获取引用文献的标题
        cited_titles = [titles[i-1] for i in citation if 1 <= i <= len(titles)]
        
        if not cited_titles:
            verification_results.append({
                'citation': citation,
                'status': 'skipped',
                'reason': '引用编号超出范围'
            })
            continue
        
        # 为每个引用的论文获取元数据
        paper_metadata_list = []
        for title in cited_titles:
            try:
                metadata_results = get_arxiv_metadata_only(title, max_results=3)
                if metadata_results:
                    # 选择最相似的结果
                    best_match = None
                    best_similarity = 0
                    for metadata in metadata_results:
                        similarity = SequenceMatcher(None, title.lower(), metadata['title'].lower()).ratio()
                        if similarity > best_similarity and similarity > 0.6:
                            best_similarity = similarity
                            best_match = metadata
                    
                    if best_match:
                        paper_metadata_list.append(best_match)
                        # 简化日志输出
                        print(f"  找到匹配: {title[:30]}... (相似度: {best_similarity:.2f})")
                    else:
                        print(f"  未找到匹配: {title[:30]}...")
                else:
                    print(f"  无搜索结果: {title[:30]}...")
            except Exception as e:
                print(f"  搜索出错: {title[:30]}... ({str(e)[:20]}...)")
        
        if not paper_metadata_list:
            verification_results.append({
                'citation': citation,
                'status': 'skipped',
                'reason': '无法获取引用文献的元数据'
            })
            continue
        
        # 使用元数据验证引用
        try:
            combined_reference = "\n\n".join([
                verify_citation_with_metadata(text, metadata) 
                for metadata in paper_metadata_list
            ])
            
            prompt = f"""你是一个文献分析助手, 你的任务是:
分析引文段落是否与参考文献的标题、摘要内容相符.
如果引文的内容与参考文献的主题、方法或结论相符, 请直接输出: <是>
否则, 请以如下格式输出: <否: '在这里给出你的理由'>

文章的引文: {text}

参考文献信息:
{combined_reference}
"""
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            
            result = response.choices[0].message.content
            
            verification_results.append({
                'citation': citation,
                'status': 'verified',
                'result': result,
                'metadata_count': len(paper_metadata_list)
            })
            
        except Exception as e:
            verification_results.append({
                'citation': citation,
                'status': 'error',
                'reason': str(e)
            })
    
    return verification_results









