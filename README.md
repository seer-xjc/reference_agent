# 📚 文献引用查证智能体

一个基于AI的学术文献引用检查工具，能够自动验证学术论文中的文献引用准确性和相关性。

## ✨ 主要功能

### 🔍 核心特性
- **自动提取参考文献**: 从PDF/DOCX文档中智能提取参考文献列表
- **引用标记识别**: 精确识别文档中的引用标记（如[1], [1,2,3]等）
- **arXiv数据库搜索**: 在arXiv学术数据库中自动搜索匹配的论文
- **AI相关性验证**: 使用大语言模型验证引用内容与参考文献的相关性
- **详细统计分析**: 提供完整的引用统计和问题分析报告

### 🎯 验证功能
- ✅ 检查引用数量完整性（是否有文献未被引用）
- ✅ 检查重复引用情况
- ✅ 验证引用内容与参考文献的相关性
- ✅ 识别可能存在问题的引用
- ✅ 生成详细的分析报告

### 🚀 运行模式
- **Web界面模式**: 友好的Gradio界面，支持文件上传和实时分析
- **命令行模式**: 适合批量处理和自动化集成
- **轻量级模式**: 使用arXiv元数据快速验证，无需下载PDF
- **标准模式**: 下载PDF进行深度内容分析

## 🛠️ 安装配置

### 环境要求
- Python 3.12
- 智谱AI API密钥

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd reference_agent
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置环境变量**
创建`.env`文件并设置API密钥：
```bash
ZHIPUAI_API_KEY=your_zhipuai_api_key_here
```

## 🎮 使用方法

### Web界面模式（推荐）

```bash
python app.py
```

然后访问 `http://localhost:7860` 打开Web界面：

1. 上传PDF或DOCX格式的学术文档
2. 选择检查模式（推荐轻量级模式）
3. 点击"开始检查"进行分析
4. 查看详细的分析结果

### 命令行模式

```bash
# 基本使用（轻量级模式）
python agent.py --doc path/to/your/document.pdf

# 完整模式（包含PDF下载）
python agent.py --doc path/to/your/document.pdf --lightweight false

# 自定义参数
python agent.py \
    --model glm-4-flash \
    --doc path/to/your/document.pdf \
    --ref path/to/references/folder \
    --lightweight \
    --skip-download
```

### 参数说明

- `--model`: AI模型选择（默认：glm-4-flash）
- `--doc`: 待检查的文档路径
- `--ref`: 参考文献PDF存储目录
- `--lightweight`: 启用轻量级模式
- `--skip-download`: 跳过PDF下载
- `--skip-pdf-verify`: 跳过PDF内容验证

## 📁 项目结构

```
reference_agent/
├── agent.py              # 命令行版本主程序
├── app.py                # Web界面版本
├── utils.py              # 核心工具函数
├── requirements.txt      # 项目依赖
├── README.md            # 项目说明
├── .env                 # 环境配置（需自行创建）
├── data/
│   ├── docs/           # 输入文档目录
│   └── references/     # 下载的参考文献PDF
└── prompts/
    └── agent_prompt    # AI提示词模板
```

## 🔧 核心模块

### agent.py
命令行版本的主要功能：
- `verify_citations_referenced()`: 检查引用完整性
- `download_literatures()`: 从arXiv下载文献PDF
- `verify_citation_sentences()`: 标准模式验证
- `verify_citation_sentences_lightweight()`: 轻量级验证

### app.py
Web界面版本特性：
- Gradio界面集成
- 实时日志显示
- 结果可视化展示
- 文件上传支持

### utils.py
核心工具函数：
- `get_reference_titles()`: 提取参考文献标题
- `get_citation_markers()`: 识别引用标记
- `search_from_arxiv()`: arXiv搜索
- `batch_verify_citations_lightweight()`: 批量轻量级验证

## 📊 分析结果说明

### 引文统计分析
- **参考文献总数**: 文档中参考文献的数量
- **引用标记总数**: 文档中发现的引用标记数量
- **未被引用文献**: 列表中未被引用的文献
- **重复引用文献**: 被多次引用的文献统计

### arXiv搜索结果
- **找到的文献**: 在arXiv中找到匹配的文献
- **未找到的文献**: 在arXiv中无法找到的文献
- **相似度评分**: 标题匹配的相似度分数

### AI验证结果
- **查验无误**: AI判断引用内容与文献相关的引用
- **需要检查**: AI判断可能存在问题的引用
- **准确率统计**: 整体验证的准确率

## ⚙️ 模式对比

| 特性 | 轻量级模式 | 标准模式 |
|------|------------|----------|
| 速度 | 快速 | 较慢 |
| 准确性 | 中等 | 高 |
| 存储需求 | 低 | 高（需下载PDF） |
| 网络依赖 | 中等 | 高 |
| 适用场景 | 快速筛查 | 精确验证 |

## 🚨 注意事项

1. **API密钥**: 需要有效的智谱AI API密钥
2. **网络连接**: arXiv搜索需要稳定的网络连接
3. **文档格式**: 支持PDF和DOCX格式的学术文档
4. **处理时间**: 文档越长，处理时间越长
5. **准确性**: AI判断仅供参考，建议人工复核重要结果

## 🤝 贡献指南

欢迎提交Issue和Pull Request来改进项目：

1. Fork本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交改动 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 📄 许可证

本项目采用MIT许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

## 🐛 问题反馈

如果遇到问题或有改进建议，请通过以下方式反馈：

1. 在GitHub上创建Issue
2. 提供详细的错误信息和复现步骤
3. 附上相关的日志输出

## 📚 更新日志

### v1.0.0
- ✅ 基础文献引用检查功能
- ✅ arXiv数据库集成
- ✅ AI相关性验证
- ✅ Web界面支持
- ✅ 轻量级模式

---

**Happy Literature Checking! 📖✨** 