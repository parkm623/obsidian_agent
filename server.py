import os
import re
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP

# 옵시디언 보관함 경로 설정
try:
    VAULT_PATH = Path(os.getenv("OBSIDIAN_VAULT_PATH", "./obsidian_vault")).resolve()
except Exception as e:
    print(f"오류: VAULT_PATH 설정 문제 - {e}")
    exit(1)

VAULT_PATH.mkdir(parents=True, exist_ok=True)


# --- 개선된 헬퍼 함수 ---

def _is_safe_path(target_path: Path) -> bool:
    """대상 경로가 VAULT_PATH 내에 있는지 확인하여 해킹(Path Traversal)을 방지합니다."""
    try:
        return target_path.resolve().is_relative_to(VAULT_PATH)
    except Exception:
        return False

def _sanitize_path(title: str) -> str:
    """폴더 구조(/)는 허용하되, 윈도우에서 금지된 특수문자만 필터링합니다."""
    normalized = title.replace('\\', '/')
    return re.sub(r'[*?:"<>|]', '_', normalized)


# MCP 서버 인스턴스
mcp = FastMCP("Obsidian Note Manager")


# --- 핵심 Tool 로직 (쓰기) ---

@mcp.tool()
def create_note(title: str, content: str, tags: any) -> str:
    """
    새로운 마크다운 노트를 생성합니다. 
    tags는 리스트(['태그1', '태그2']) 또는 쉼표로 구분된 문자열('태그1, 태그2') 모두 허용합니다.
    """
    final_tags = []
    if isinstance(tags, list):
        final_tags = tags
    elif isinstance(tags, str):
        final_tags = [t.strip() for t in tags.split(',') if t.strip()]
    
    sanitized_title = _sanitize_path(title)
    file_path = VAULT_PATH / f"{sanitized_title}.md"

    if not _is_safe_path(file_path):
        return f"경로 접근 오류: 허용된 보관함 외부입니다."

    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = VAULT_PATH / f"{sanitized_title}_{timestamp}.md"

    today = datetime.now().strftime("%Y-%m-%d")
    tags_yaml = "".join([f"\n  - {tag}" for tag in final_tags])
    frontmatter = f"---\ndate: {today}\ntags:{tags_yaml}\n---\n\n"

    try:
        file_path.write_text(frontmatter + content, encoding='utf-8')
        return f"성공: '{file_path.relative_to(VAULT_PATH)}' 생성 완료."
    except OSError as e:
        return f"파일 쓰기 오류: {e}"

@mcp.tool()
def append_to_note(title: str, content: str) -> str:
    """기존 노트 끝에 내용을 추가합니다. 슬래시(/)를 사용해 폴더를 지정할 수 있습니다."""
    sanitized_title = _sanitize_path(title)
    file_path = VAULT_PATH / f"{sanitized_title}.md"

    if not _is_safe_path(file_path):
        return f"경로 접근 오류: 허용된 보관함 외부입니다."

    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        needs_newline = False
        if file_path.exists() and file_path.stat().st_size > 0:
            with file_path.open('rb') as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b'\n':
                    needs_newline = True

        with file_path.open('a', encoding='utf-8') as f:
            if needs_newline:
                f.write('\n')
            f.write(f"\n{content}\n")
        
        return f"성공: '{file_path.relative_to(VAULT_PATH)}' 파일에 내용 추가 완료."
    except OSError as e:
        return f"파일 추가 오류: {e}"


# --- 핵심 Tool 로직 (읽기 및 검색: 그래프 연결용) ---

@mcp.tool()
def list_notes() -> list[str]:
    """
    현재 보관함에 있는 모든 마크다운 파일의 목록을 가져옵니다.
    기존 문서들과의 연결고리를 찾을 때 유용합니다.
    """
    notes = []
    for path in VAULT_PATH.rglob("*.md"):
        notes.append(str(path.relative_to(VAULT_PATH)).replace(".md", ""))
    return notes

@mcp.tool()
def read_note(title: str) -> str:
    """
    지정된 제목의 노트 내용을 읽어옵니다.
    기존 노트의 맥락을 파악하여 새로운 링크를 만들 때 사용합니다.
    """
    sanitized_title = _sanitize_path(title)
    file_path = VAULT_PATH / f"{sanitized_title}.md"
    
    if not _is_safe_path(file_path) or not file_path.exists():
        return f"오류: '{title}' 노트를 찾을 수 없거나 접근할 수 없습니다."
    
    try:
        return file_path.read_text(encoding='utf-8')
    except Exception as e:
        return f"파일 읽기 오류: {e}"

@mcp.tool()
def search_notes(query: str) -> list[str]:
    """
    보관함 내의 모든 노트를 검색하여 특정 키워드가 포함된 파일 목록을 반환합니다.
    관련 있는 기존 노트를 찾아 위키링크([[링크]])를 걸 때 필수적입니다.
    """
    results = []
    for path in VAULT_PATH.rglob("*.md"):
        try:
            content = path.read_text(encoding='utf-8')
            if query.lower() in content.lower() or query.lower() in path.name.lower():
                results.append(str(path.relative_to(VAULT_PATH)).replace(".md", ""))
        except:
            continue
    return results


if __name__ == "__main__":
    # 구글 클라우드에서 접속할 수 있도록 SSE(Server-Sent Events) 모드로 실행
    # 기본 포트는 8000번입니다.
    print(f"🚀 옵시디언 MCP 서버 시작! (보관함: {VAULT_PATH})")
    mcp.run(transport="sse")