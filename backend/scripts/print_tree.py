import os

def print_tree(directory, prefix="", ignore_dirs=None, ignore_files=None):
    # 需要忽略的常见无用目录
    if ignore_dirs is None:
        ignore_dirs = {
            '.git', 'node_modules', 'venv', '.venv', 'env', 
            '__pycache__', '.idea', '.vscode', 'dist', 'build'
        }
    # 需要忽略的常见无用文件
    if ignore_files is None:
        ignore_files = {'.DS_Store', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml'}

    try:
        items = sorted(os.listdir(directory))
    except PermissionError:
        return

    # 过滤掉不需要显示的目录和文件
    items = [item for item in items if item not in ignore_dirs and item not in ignore_files]

    for i, item in enumerate(items):
        path = os.path.join(directory, item)
        is_last = i == (len(items) - 1)
        
        # 打印当前层级
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{item}")
        
        # 如果是目录，递归往下打印
        if os.path.isdir(path):
            extension = "    " if is_last else "│   "
            print_tree(path, prefix + extension, ignore_dirs, ignore_files)

if __name__ == "__main__":
    # "." 代表当前目录。请确保在项目根目录下运行此脚本
    project_root = "." 
    print(f"📦 Project Tree: {os.path.abspath(project_root)}")
    print("=" * 40)
    print_tree(project_root)
    print("=" * 40)