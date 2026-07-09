# creating-my-own-git

A from-scratch implementation of Git's core plumbing in Python — built to understand 
how Git actually works under the hood, without using GitPython, libgit2, or any 
Git-wrapping library.

## What it does

Git is fundamentally a content-addressable filesystem with a version control layer 
on top. This project reimplements that foundation: objects are hashed with SHA-1, 
compressed with zlib, and stored in a `.pygit/objects` directory exactly like real Git.

## Implemented commands

- `init` — initializes a new repository (.pygit directory structure)
- `hash-object` — computes SHA-1 hash and stores a file as a blob object
- `cat-file` — reads and prints the contents of a stored object
- `add` — stages files by writing blob objects and updating the index
- `commit` — creates a commit object linking a tree snapshot, parent commit, and message

## Usage

```bash
python main.py init
python main.py hash-object <file>
python main.py cat-file <hash>
python main.py add <file>
python main.py commit -m "message"
```

## What I learned

Building this required understanding Git's object model (blobs, trees, commits), 
content-addressable storage via SHA-1 hashing, and how refs/HEAD tie together to 
form the commit graph — concepts that are usually hidden behind Git's CLI.

## Roadmap

- [ ] `log` — walk commit history via parent pointers
- [ ] `diff` — compare tree/blob contents
- [ ] `branch` / `checkout` — ref manipulation
