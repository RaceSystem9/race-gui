import json
from openpyxl import load_workbook

# 엑셀 파일 읽기
wb = load_workbook("team_info.xlsx", data_only=True)
ws = wb.active

teams = []

# 첫 번째 행은 제목
for row in ws.iter_rows(min_row=2, values_only=True):

    if row[0] is None:
        continue

    # 팀원 목록 생성
    members = []

    for i in range(5):
        base = 4 + i * 4

        if row[base] is None:
            continue

        members.append({
            "name": row[base],
            "school": row[base + 1],
            "department": row[base + 2],
            "grade": row[base + 3]
        })

    # 원하는 순서대로 JSON 생성
    team = {
        "team_no": int(row[0]),
        "team_name": row[1],
        "school": row[2],
        "num_of_members": len(members),
        "members": members
    }

    teams.append(team)

# JSON 저장
with open("team_info.json", "w", encoding="utf-8") as f:
    json.dump(teams, f, ensure_ascii=False, indent=4)

print(f"team_info.xlsx 파일을 읽어 처리해서")
print(f"{len(teams)}개 팀 정보를 team_info.json으로 저장했습니다.")