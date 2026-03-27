# 파일명: test_server.py

# 메인 파일(server.py)에서 필요한 함수와 변수만 가져옵니다.
from server import create_note, append_to_note, VAULT_PATH

def run_tests():
    print(f"옵시디언 보관함 경로: {VAULT_PATH}\n")
    print("--- 🚀 자동화 테스트 시작 ---\n")

    # 1. Notes Tool 테스트 (새 노트 생성)
    print("1. 새 노트 생성 테스트")
    res1 = create_note(
        title="첫번째 테스트 노트", 
        content="# 안녕하세요\n\n이것은 첫번째 테스트입니다.", 
        tags=["테스트", "gemini"]
    )
    print(f"결과: {res1}\n")

    # 2. append_to_note Tool 테스트 (기존 노트에 내용 추가)
    print("2. 기존 노트에 내용 추가 테스트")
    res2 = append_to_note(
        title="첫번째 테스트 노트", 
        content="\n\n---\n\n내용을 추가해봤습니다."
    )
    print(f"결과: {res2}\n")

    # 3. Notes Tool 테스트 (동일한 제목으로 노트 생성)
    print("3. 동일한 제목으로 노트 생성 (타임스탬프) 테스트")
    res3 = create_note(
        title="첫번째 테스트 노트", 
        content="# 중복된 제목\n\n타임스탬프가 붙어야 합니다.", 
        tags=["중복"]
    )
    print(f"결과: {res3}\n")

    # 4. Notes Tool 테스트 (특수문자가 포함된 제목)
    print("4. 특수문자가 포함된 제목 테스트")
    res4 = create_note(
        title="특수문자/테스트?파일!", 
        content="# 특수문자 테스트", 
        tags=["special-chars"]
    )
    print(f"결과: {res4}\n")

    # 5. append_to_note Tool 테스트 (존재하지 않는 노트)
    print("5. 존재하지 않는 노트에 내용 추가 (새로 생성) 테스트")
    res5 = append_to_note(
        title="새로 만들어질 노트", 
        content="append_to_note로 새로 만든 파일입니다."
    )
    print(f"결과: {res5}\n")

    print("--- 🎉 테스트 완료! obsidian_vault 폴더를 확인해 보세요! ---")

if __name__ == "__main__":
    run_tests()