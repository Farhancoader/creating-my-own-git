import argparse
import hashlib
from pathlib import Path
import sys
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
    

class Repository:


    def __init__(self,path="."):
        self.path = Path(path).resolve()
        self.git_dir = self.path / ".pygit"
        self.objects_dir = self.git_dir / "objects"
        self.refs_dir = self.git_dir / "refs"
        self.head_file = self.git_dir / "HEAD"
        self.index_file = self.git_dir / "index"


    def init(self)-> bool:
        if self.git_dir.exists():
            print(f"Repository already exists in {self.git_dir}")
            return False
        self.git_dir.mkdir(parents=True, exist_ok=True)
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.refs_dir.mkdir(parents=True, exist_ok=True)
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
        index[str(file_path)] = blob_hash
        self.save_index(index)
        print(f"Added file {file_path} to the repository with hash {blob_hash}.")

    #def add_directory(self, dir_path: Path):

    
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
    


def main():
    parser = argparse.ArgumentParser(description="A simple command-line tool.")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    init_parser = subparsers.add_parser("init", help="Initialize the application")
    add_parser = subparsers.add_parser("add", help="Add a file to the repository")
    
    add_parser.add_argument("paths", nargs="+", help="Paths of files to add")
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
    except Exception as e:
        print(f"An error occurred: {e}")
main()

