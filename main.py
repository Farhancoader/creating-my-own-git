import argparse
import hashlib
from pathlib import Path
import sys
from time import time
from tkinter import SEL
import json
import zlib

class gitobjects:
    def __init__(self,obj_type : str,content:bytes):
        
        self.type = obj_type
        self.content = content
        self.hash = self.compute_hash()
    
    def compute_hash(self) -> str:
        return self.hash_object()
    
    def hash_object(self)->str:
        header = f"{self.type} {len(self.content)}\0".encode()
        return hashlib.sha1(header + self.content).hexdigest()
    
    def serialize(self)->bytes:
        header = f"{self.type} {len(self.content)}\0".encode()
        return zlib.compress(header + self.content)
    
    @classmethod
    def deserialize(cls, data: bytes):
        decompressed_data = zlib.decompress(data)
        header_end_index = decompressed_data.index(b'\0')
        header = decompressed_data[:header_end_index].decode()

        obj_type, size_str = header.split(' ')

        size = int(size_str)
        obj_content = decompressed_data[header_end_index + 1:]

        if len(obj_content) != size:
            raise ValueError("Content size does not match the size specified in the header.")   
        
        return cls(obj_type, obj_content)

class Blob(gitobjects):
    def __init__(self, content: bytes):
        super().__init__("blob", content)
    
    def get_content(self) -> bytes:
        return self.content
    
class Tree(gitobjects):
    def __init__(self, entries: list[tuple[str, str, str]] = None):
        self.entries = entries or []
        raw_content = self.make_raw_content()
        super().__init__("tree", raw_content)

    def make_raw_content(self) -> bytes:
        return b''.join(
            f"{mode} {name}\0".encode() + bytes.fromhex(obj_hash)
            for mode, name, obj_hash in self.entries
        )
    
    def add_entry(self, mode: str, name: str, obj_hash: str):
        self.entries.append((mode, name, obj_hash))
        self.content = self.make_raw_content()
        self.hash = self.compute_hash()

    @classmethod
    def deserialize(cls, content: bytes):
        tree = cls()
        i = 0
        while i < len(content):
            mode_end = content.find(b' ', i)
            mode = content[i:mode_end].decode()
            name_end = content.find(b'\0', mode_end)
            name = content[mode_end + 1:name_end].decode()
            obj_hash = content[name_end + 1:name_end + 21].hex()
            tree.add_entry(mode, name, obj_hash)
            i = name_end + 21

        return tree
    
class commit(gitobjects):
    def __init__(self,tree_hash:str,parent_hash:str,author:str,committer:str,message:str,timestamp:int):
        self.tree_hash = tree_hash
        self.parent_hash = parent_hash
        self.author = author
        self.committer = committer
        self.message = message
        self.timestamp = timestamp or int(time())
        raw_content = self.make_raw_content()
        super().__init__("commit",raw_content)
    
    def make_raw_content(self)->bytes:
        lines = [
            f"tree {self.tree_hash}"]
        for parent in self.parent_hash:
            lines.append(f"parent {parent}")
        lines.append(f"author {self.author} {self.timestamp}+0000")
        lines.append(f"committer {self.committer} {self.timestamp}+0000")
        lines.append("")
        lines.append(self.message)
        return "\n".join(lines).encode()
    
    @classmethod
    def from_content(cls, content: bytes):
        lines = content.decode().splitlines()
        tree_hash = lines[0].split()[1]
        parent_hashes = [line.split()[1] for line in lines[1:] if line.startswith("parent")]
        author_line = next(line for line in lines if line.startswith("author"))
        author = author_line.split()[1]
        committer_line = next(line for line in lines if line.startswith("committer"))
        committer = committer_line.split()[1]
        message_index = lines.index("") + 1
        message = "\n".join(lines[message_index:])
        timestamp = int(author_line.split()[2].split('+')[0].split('-')[0])
        return cls(tree_hash, parent_hashes, author, committer, message, timestamp)  

class Repository:


    def __init__(self,path="."):
        self.path = Path(path).resolve()
        self.git_dir = self.path / ".pygit"
        self.objects_dir = self.git_dir / "objects"
        self.refs_dir = self.git_dir / "refs"
        self.heads_dir = self.refs_dir / "heads"
        self.head_file = self.git_dir / "HEAD"
        self.index_file = self.git_dir / "index"


    def init(self)-> bool:
        if self.git_dir.exists():
            print(f"Repository already exists in {self.git_dir}")
            return False
        self.git_dir.mkdir(parents=True, exist_ok=True)
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        self.heads_dir.mkdir(parents=True, exist_ok=True)
        self.head_file.touch(exist_ok=True)

        self.head_file.write_text("ref: refs/heads/master\n")
        self.save_index({})

        self.index_file.write_text(json.dumps({},indent=4))
        print(f"Initialized empty pygit repository in {self.git_dir}")

        return True
    
    def store_object(self, obj: gitobjects) -> str:
        obj_hash = obj.hash_object()
        obj_path = self.objects_dir / obj_hash[:2] / obj_hash[2:]

        obj_path.parent.mkdir(parents=True, exist_ok=True)
        if not obj_path.exists():
            obj_path.write_bytes(obj.serialize())

        return obj_hash
    
    def load_index(self) -> dict[str,str]:
        if not self.index_file.exists():
            return {}
        try:
            return json.loads(self.index_file.read_text())
        except json.JSONDecodeError:
            print(f"Error: The index file {self.index_file} is corrupted.")
            return {}
        
    def save_index(self, index: dict[str,str]):
        self.index_file.write_text(json.dumps(index, indent=4))
    
    def add_file(self, file_path: Path):
        full_path = self.path / file_path
        if not full_path.exists():
            raise FileNotFoundError(f"File {full_path} does not exist.")
        
        content = full_path.read_bytes()
        blob = Blob(content)
        blob_hash = self.store_object(blob)
        index = self.load_index()
        rel_path = file_path.resolve().relative_to(self.path).as_posix()
        index[rel_path] = blob_hash
        self.save_index(index)
        print(f"Added file {rel_path} to the repository with hash {blob_hash}.")

    def add_directory(self, dir_path: Path):
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory {dir_path} does not exist.")
        if not dir_path.is_dir():
            raise ValueError(f"Path {dir_path} is not a directory.")
        index = self.load_index()
        added_count = 0
        for path in dir_path.rglob('*'):
            if ".pygit" in path.parts or ".git" in path.parts:
                continue
            if path.is_file():
                content = path.read_bytes()
                blob = Blob(content)
                blob_hash = self.store_object(blob)
                rel_path = path.resolve().relative_to(self.path).as_posix()
                index[rel_path] = blob_hash
                added_count += 1
        self.save_index(index)
        print(f"Added {added_count} files from directory {dir_path} to the repository.")
    
    def add(self,path:str)->bool:
        full_path = self.path/path
        if not full_path.exists():
            raise FileNotFoundError(f"Path {full_path} does not exist.")
        if full_path.is_file():
            self.add_file(full_path)
        elif full_path.is_dir():
            self.add_directory(full_path)
        else:
            raise ValueError(f"Path {full_path} is neither a file nor a directory.")
        

    def create_tree(self) -> str:
        index = self.load_index()
        if not index:
            tree = Tree()
            return self.store_object(tree)
        
        dirs, files = {}, {}
        for path, blob_hash in index.items():
            parts = path.replace('\\', '/').split('/')
            if len(parts) == 1:
                files[parts[0]] = blob_hash
            else:
                dir_name = parts[0]
                if dir_name not in dirs:
                    dirs[dir_name] = {}

                current = dirs[dir_name]

                for part in parts[1:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]

                current[parts[-1]] = blob_hash

        def create_tree_recursive(entries: dict) -> str:
            tree_entries = []
            for name, content in entries.items():
                if isinstance(content, dict):
                    subtree_hash = create_tree_recursive(content)
                    tree_entries.append(("40000", name, subtree_hash))
                else:
                    tree_entries.append(("100644", name, content))
            tree = Tree(tree_entries)
            return self.store_object(tree)

        root_entries = {**files}
        for dir_name, dir_content in dirs.items():
            root_entries[dir_name] = dir_content

        return create_tree_recursive(root_entries)

    def get_current_branch(self) -> str:
        if not self.head_file.exists():
            return "master"
        head_content = self.head_file.read_text().strip()
        if head_content.startswith("ref:"):
            ref_str = head_content.split("ref:")[1].strip()
            if ref_str.startswith("refs/heads/"):
                return ref_str[11:]
            return ref_str
        return "HEAD"
    
    def get_branch_commit(self) -> str:
        if not self.head_file.exists():
            return None
        head_content = self.head_file.read_text().strip()
        if head_content.startswith("ref:"):
            ref_path = self.git_dir / head_content.split("ref:")[1].strip()
            if ref_path.exists():
                return ref_path.read_text().strip()
        else:
            return head_content
        return None

    def commit(self, message: str, author: str = "Unknown") -> bool:
        tree_hash = self.create_tree()
        current_branch = self.get_current_branch()
        parent_commit = self.get_branch_commit()
        parent_hashes = [parent_commit] if parent_commit else []
        
        timestamp = int(time())
        commit_obj = commit(
            tree_hash=tree_hash,
            parent_hash=parent_hashes,
            author=author,
            committer=author,
            message=message,
            timestamp=timestamp
        )
        commit_hash = self.store_object(commit_obj)
        
        # Update ref or HEAD
        head_content = self.head_file.read_text().strip()
        if head_content.startswith("ref:"):
            # Update the branch ref
            ref_path = self.git_dir / head_content.split("ref:")[1].strip()
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_text(commit_hash + "\n")
        else:
            # Detached HEAD, update HEAD directly
            self.head_file.write_text(commit_hash + "\n")
            
        print(f"[{current_branch} {commit_hash[:7]}] {message}")
        return True

    def load_object(self, obj_hash: str):
        obj_path = self.objects_dir / obj_hash[:2] / obj_hash[2:]
        if not obj_path.exists():
            raise FileNotFoundError(f"Object {obj_hash} not found.")
        compressed_data = obj_path.read_bytes()
        decompressed_data = zlib.decompress(compressed_data)
        
        header_end = decompressed_data.index(b'\0')
        header = decompressed_data[:header_end].decode()
        obj_type, size_str = header.split(' ')
        size = int(size_str)
        content = decompressed_data[header_end + 1:]
        
        if len(content) != size:
            raise ValueError(f"Content length mismatch for object {obj_hash}")
            
        if obj_type == "blob":
            return Blob(content)
        elif obj_type == "tree":
            return Tree.deserialize(content)
        elif obj_type == "commit":
            return commit.from_content(content)
        else:
            raise ValueError(f"Unknown object type: {obj_type}")

    def get_tree_entries(self, tree_hash: str) -> dict[str, str]:
        entries = {}
        def recurse(t_hash: str, current_path: str):
            try:
                tree_obj = self.load_object(t_hash)
            except Exception:
                return
            if not isinstance(tree_obj, Tree):
                return
            for mode, name, obj_hash in tree_obj.entries:
                path = f"{current_path}/{name}" if current_path else name
                if mode == "40000":  # Tree
                    recurse(obj_hash, path)
                else:  # Blob
                    entries[path] = obj_hash
        recurse(tree_hash, "")
        return entries

    def log(self):
        commit_hash = self.get_branch_commit()
        if not commit_hash:
            print("No commits yet.")
            return
            
        while commit_hash:
            try:
                commit_obj = self.load_object(commit_hash)
            except Exception as e:
                print(f"Error loading commit {commit_hash}: {e}")
                break
                
            from datetime import datetime
            dt = datetime.fromtimestamp(commit_obj.timestamp)
            date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            print(f"commit {commit_hash}")
            print(f"Author: {commit_obj.author}")
            print(f"Date:   {date_str}\n")
            print(f"    {commit_obj.message}\n")
            
            if commit_obj.parent_hash:
                commit_hash = commit_obj.parent_hash[0]
            else:
                commit_hash = None

    def create_branch(self, name: str) -> bool:
        commit_hash = self.get_branch_commit()
        if not commit_hash:
            print("Fatal: Not a valid object name: 'master'. Cannot create branch without a commit.")
            return False
        branch_file = self.heads_dir / name
        if branch_file.exists():
            print(f"Fatal: A branch named '{name}' already exists.")
            return False
        branch_file.parent.mkdir(parents=True, exist_ok=True)
        branch_file.write_text(commit_hash + "\n")
        print(f"Branch '{name}' created at commit {commit_hash[:7]}.")
        return True

    def list_branches(self):
        if not self.heads_dir.exists():
            print("No branches found.")
            return
        current_branch = self.get_current_branch()
        branches = sorted([p.name for p in self.heads_dir.iterdir() if p.is_file()])
        for b in branches:
            if b == current_branch:
                print(f"* {b}")
            else:
                print(f"  {b}")

    def delete_branch(self, name: str) -> bool:
        branch_file = self.heads_dir / name
        if not branch_file.exists():
            print(f"Error: branch '{name}' not found.")
            return False
        current_branch = self.get_current_branch()
        if name == current_branch:
            print(f"Error: Cannot delete the branch '{name}' which you are currently on.")
            return False
        branch_file.unlink()
        print(f"Deleted branch {name}.")
        return True

    def checkout(self, target: str) -> bool:
        branch_file = self.heads_dir / target
        is_branch = branch_file.exists()
        
        if is_branch:
            commit_hash = branch_file.read_text().strip()
        else:
            commit_hash = target
            if len(commit_hash) < 40:
                matching = []
                if self.objects_dir.exists():
                    for prefix_dir in self.objects_dir.iterdir():
                        if prefix_dir.is_dir() and len(prefix_dir.name) == 2:
                            if commit_hash.startswith(prefix_dir.name):
                                for f in prefix_dir.iterdir():
                                    full_hash = prefix_dir.name + f.name
                                    if full_hash.startswith(commit_hash):
                                        try:
                                            obj = self.load_object(full_hash)
                                            if isinstance(obj, commit):
                                                matching.append(full_hash)
                                        except Exception:
                                            pass
                if len(matching) == 1:
                    commit_hash = matching[0]
                elif len(matching) > 1:
                    print(f"Error: Short SHA1 {target} is ambiguous.")
                    return False
            
            try:
                commit_obj = self.load_object(commit_hash)
                if not isinstance(commit_obj, commit):
                    print(f"Error: Object {commit_hash} is not a commit.")
                    return False
            except Exception:
                print(f"Error: pathspec or branch/commit '{target}' did not match any file(s) known to git.")
                return False

        commit_obj = self.load_object(commit_hash)
        target_entries = self.get_tree_entries(commit_obj.tree_hash)
        current_index = self.load_index()
        
        # Remove files from index not in target tree
        for path_str in list(current_index.keys()):
            if path_str not in target_entries:
                file_path = self.path / path_str
                if file_path.exists():
                    file_path.unlink()
                    parent = file_path.parent
                    while parent != self.path:
                        if not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                        else:
                            break
                            
        # Restore/write target files
        for path_str, blob_hash in target_entries.items():
            file_path = self.path / path_str
            file_path.parent.mkdir(parents=True, exist_ok=True)
            blob_obj = self.load_object(blob_hash)
            file_path.write_bytes(blob_obj.content)
            
        self.save_index(target_entries)
        
        if is_branch:
            self.head_file.write_text(f"ref: refs/heads/{target}\n")
            print(f"Switched to branch '{target}'")
        else:
            self.head_file.write_text(commit_hash + "\n")
            print(f"Note: switching to '{target}'. You are in 'detached HEAD' state.")
            print(f"HEAD is now at {commit_hash[:7]}...")
            
        return True

    def status(self):
        current_branch = self.get_current_branch()
        if self.head_file.exists():
            head_content = self.head_file.read_text().strip()
            if head_content.startswith("ref:"):
                print(f"On branch {current_branch}")
            else:
                print(f"HEAD detached at {head_content[:7]}")
        else:
            print(f"On branch {current_branch}")
            
        parent_commit_hash = self.get_branch_commit()
        head_entries = {}
        if parent_commit_hash:
            try:
                parent_commit = self.load_object(parent_commit_hash)
                head_entries = self.get_tree_entries(parent_commit.tree_hash)
            except Exception:
                pass
                
        index_entries = self.load_index()
        
        working_files = {}
        for path in self.path.rglob('*'):
            if ".pygit" in path.parts or ".git" in path.parts:
                continue
            if path.is_file():
                rel_path = path.resolve().relative_to(self.path).as_posix()
                working_files[rel_path] = path
                
        staged_new = []
        staged_modified = []
        staged_deleted = []
        
        for path in index_entries:
            if path not in head_entries:
                staged_new.append(path)
            elif index_entries[path] != head_entries[path]:
                staged_modified.append(path)
                
        for path in head_entries:
            if path not in index_entries:
                staged_deleted.append(path)
                
        unstaged_modified = []
        unstaged_deleted = []
        
        for path in index_entries:
            if path not in working_files:
                unstaged_deleted.append(path)
            else:
                w_path = working_files[path]
                content = w_path.read_bytes()
                blob = Blob(content)
                if blob.hash != index_entries[path]:
                    unstaged_modified.append(path)
                    
        untracked = []
        for path in working_files:
            if path not in index_entries:
                untracked.append(path)
                
        print_staged = staged_new or staged_modified or staged_deleted
        print_unstaged = unstaged_modified or unstaged_deleted
        
        if print_staged:
            print("\nChanges to be committed:")
            for path in staged_new:
                print(f"\tnew file:   {path}")
            for path in staged_modified:
                print(f"\tmodified:   {path}")
            for path in staged_deleted:
                print(f"\tdeleted:    {path}")
                
        if print_unstaged:
            print("\nChanges not staged for commit:")
            for path in unstaged_modified:
                print(f"\tmodified:   {path}")
            for path in unstaged_deleted:
                print(f"\tdeleted:    {path}")
                
        if untracked:
            print("\nUntracked files:")
            for path in sorted(untracked):
                print(f"\t{path}")
                
        if not print_staged and not print_unstaged and not untracked:
            print("\nnothing to commit, working tree clean")

        

    


def main():
    parser = argparse.ArgumentParser(description="A simple command-line tool.")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    init_parser = subparsers.add_parser("init", help="Initialize the application")
    add_parser = subparsers.add_parser("add", help="Add a file to the repository")
    commit_parser = subparsers.add_parser("commit", help="Commit changes to the repository")
    
    add_parser.add_argument("paths", nargs="+", help="Paths of files to add")
    commit_parser.add_argument("-message","-m", help="Commit message")
    commit_parser.add_argument("-author","-a", help="Author of the commit")

    log_parser = subparsers.add_parser("log", help="Show commit history")
    
    branch_parser = subparsers.add_parser("branch", help="List, create, or delete branches")
    branch_parser.add_argument("name", nargs="?", help="Name of branch to create")
    branch_parser.add_argument("-d", "--delete", help="Delete branch")

    checkout_parser = subparsers.add_parser("checkout", help="Switch branches or restore working tree files")
    checkout_parser.add_argument("target", help="Branch name or commit hash to checkout")

    status_parser = subparsers.add_parser("status", help="Show the working tree status")


    args =parser.parse_args()
    if not args.command:
        parser.print_help()
        return 
    try:
        if args.command == "init":
            repo = Repository()
            repo.init()
        elif args.command == "add":
            repo = Repository()
            if not repo.git_dir.exists():
                print("Not a pygit repository. Please run 'init' first.")
                return
            for path in args.paths:
                file_path = Path(path).resolve()
                if not file_path.exists():
                    print(f"File {file_path} does not exist.")
                    continue
                repo.add(str(file_path))
        elif args.command == "commit":
            repo = Repository()
            if not repo.git_dir.exists():
                print("Not a pygit repository. Please run 'init' first.")
                return
            if not args.message:
                print("Error: Commit message is required.")
                return
            author = args.author if args.author else "Unknown"
            repo.commit(args.message, author)
        elif args.command == "log":
            repo = Repository()
            if not repo.git_dir.exists():
                print("Not a pygit repository. Please run 'init' first.")
                return
            repo.log()
        elif args.command == "branch":
            repo = Repository()
            if not repo.git_dir.exists():
                print("Not a pygit repository. Please run 'init' first.")
                return
            if args.delete:
                repo.delete_branch(args.delete)
            elif args.name:
                repo.create_branch(args.name)
            else:
                repo.list_branches()
        elif args.command == "checkout":
            repo = Repository()
            if not repo.git_dir.exists():
                print("Not a pygit repository. Please run 'init' first.")
                return
            repo.checkout(args.target)
        elif args.command == "status":
            repo = Repository()
            if not repo.git_dir.exists():
                print("Not a pygit repository. Please run 'init' first.")
                return
            repo.status()

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
main()

