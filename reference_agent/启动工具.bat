@echo off
chcp 65001 >nul
echo.
echo ================================================
echo           文献引用检查工具启动器
echo ================================================
echo.

echo 🔍 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: 未找到Python环境
    echo 请确保已安装Python 3.8或更高版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo ✅ Python环境检查通过
echo.

echo 🚀 启动诊断脚本...
python start_app.py

if errorlevel 1 (
    echo.
    echo ❌ 启动失败，请检查错误信息
    echo.
    echo 💡 常见解决方案：
    echo 1. 设置API密钥: set ZHIPUAI_API_KEY=your_key_here
    echo 2. 安装依赖: pip install -r requirements.txt
    echo 3. 检查端口占用: netstat -an ^| findstr :7860
    echo.
    pause
    exit /b 1
)

pause 