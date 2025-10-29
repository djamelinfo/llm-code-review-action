\
#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import textwrap
from pathlib import Path
import requests

DEFAULT_PROMPT = """You are a meticulous code reviewer. Read the provided Git patch. 
Return a concise, actionable review in Markdown with sections:

- Key Risks (security, reliability, data-loss, secrets, PII, auth)
- Bugs & Smells (concrete lines, why it's an issue)
- Performance & Scalability (micro and macro)
- Style & Clarity (naming, comments, dead code)
- Suggested Changes (minimal diffs/patches in fenced code blocks)

Rules:
- Reference files and line numbers based on the patch context.
- If everything looks good, explicitly say so and add a brief praise.
- NEVER include private tokens or secrets in examples.
"""

def sh(cmd: str) -> str:
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        raise SystemExit(res.returncode)
    return res.stdout

def get_event():
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        print("GITHUB_EVENT_PATH missing; this action must run on pull_request events." + event_path, file=sys.stderr)
        sys.exit(1)
    with open(event_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_repo_info():
    full = os.getenv("GITHUB_REPOSITORY", "")
    if not full or "/" not in full:
        print("GITHUB_REPOSITORY not found.", file=sys.stderr)
        sys.exit(1)
    owner, repo = full.split("/", 1)
    return owner, repo

def _ref_exists(ref: str) -> bool:
     try:
         sh(f"git rev-parse --verify --quiet {ref}")
         return True
     except SystemExit:
         return False
 
def get_diff(base_ref: str, head_sha: str) -> str:
     # 1) Try to ensure we have the base branch from origin (best case)
     try:
         sh(f"git fetch --no-tags --depth=1 origin {base_ref}")
     except SystemExit:
         # In act/local runs, 'origin' may be missing. Try to add a local origin.
         try:
             sh("git remote add origin .")
             sh(f"git fetch --no-tags --depth=1 origin {base_ref}")
         except SystemExit:
             pass
 
     candidates = [
         f"origin/{base_ref}",
         base_ref,
         # Fallback to the checked-out base commit if present in event (handled below)
     ]
 
     # 2) Prefer three-dot diff if we have a valid base ref
     for base in candidates:
         if _ref_exists(base):
             try:
                 return sh(f"git diff --unified=0 --no-color {base}...{head_sha}").strip()
             except SystemExit:
                 pass
 
     # 3) Try explicit merge-base
     try:
         mb = sh(f"git merge-base {head_sha} {base_ref}").strip()
         if mb:
             return sh(f"git diff --unified=0 --no-color {mb}..{head_sha}").strip()
     except SystemExit:
         pass
 
     # 4) Last resort: diff last commit (works for single-commit PRs in tests)
     try:
         return sh("git diff --unified=0 --no-color HEAD~1..HEAD").strip()
     except SystemExit:
         return ""
def chunk_text(text: str, max_chars: int):
    if len(text) <= max_chars:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        h = text.rfind("\\n@@", start, end)
        if h == -1 or h <= start + 1000:
            h = text.rfind("\\ndiff --git ", start, end)
        if h == -1 or h <= start + 1000:
            h = end
        chunks.append(text[start:h])
        start = h
    return [c for c in chunks if c.strip()]

def call_ollama(host: str, model: str, system_prompt: str, user_content: str, temperature: float):
    url = host.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    r = requests.post(url, json=payload, timeout=300)
    r.raise_for_status()
    data = r.json()
    return data.get("message", {}).get("content", "").strip() or data.get("response", "")

def post_issue_comment(base_url: str, token: str, owner: str, repo: str, pr_number: int, body_md: str):
    url = base_url.rstrip("/") + f"/api/v1/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {token}"}
    resp = requests.post(url, headers=headers, json={"body": body_md}, timeout=120)
    if resp.status_code >= 300:
        print(f"Failed to post comment: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)

def main():
    event = get_event()
    if event.get("pull_request") is None:
        print("Not a pull_request event.", file=sys.stderr)
        sys.exit(1)

    pr = event["pull_request"]
    pr_number = pr["number"]
    base_ref = pr["base"]["ref"]
    head_sha = pr["head"]["sha"]

    owner, repo = get_repo_info()

    base_url = os.getenv("INPUT_GITEA_BASE_URL")
    token = os.getenv("INPUT_GITEA_TOKEN")
    ollama_host = os.getenv("INPUT_OLLAMA_HOST")
    ollama_model = os.getenv("INPUT_OLLAMA_MODEL")
    temperature = float(os.getenv("INPUT_TEMPERATURE", "0.2"))
    max_context_chars = int(os.getenv("INPUT_MAX_CONTEXT_CHARS", "20000"))
    system_prompt = os.getenv("INPUT_SYSTEM_PROMPT") or DEFAULT_PROMPT

    print(f"[action] Reviewing PR #{pr_number} base={base_ref} head={head_sha} with model={ollama_model}")

    diff = get_diff(base_ref, head_sha)
    if not diff:
        post_issue_comment(base_url, token, owner, repo, pr_number, "No code changes detected in the diff.")
        return

    chunks = chunk_text(diff, max_context_chars)
    sections = []
    for i, chunk in enumerate(chunks, 1):
        user_content = textwrap.dedent(f"""
        Review the following git diff and provide feedback.

        <diff>
        {chunk}
        </diff>
        """).strip()
        try:
            reply = call_ollama(ollama_host, ollama_model, system_prompt, user_content, temperature)
        except Exception as e:
            reply = f"Chunk {i} review failed: `{e}`"
        sections.append(f"""
                        
                        ### Chunk {i}/{len(chunks)} 
                        # 
                        # {reply}""")

    body = """# 🤖 Ollama Code Review:""" + """
    
                        ---
                        
                        """.join(sections)
    if len(body) > 18000:
        body = """_Note: Review truncated due to size limits.
        
                """ + body[-18000:]

    post_issue_comment(base_url, token, owner, repo, pr_number, body)
    print("[action] Review posted.")

if __name__ == "__main__":
    main()
