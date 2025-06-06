from datetime import datetime
from decimal import Decimal
from typing import Optional

import pymysql
from fastapi import FastAPI, File, UploadFile, Request, Form, Query, Path, Body
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import pandas as pd
import msoffcrypto
import io
import re
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from starlette.responses import RedirectResponse

app = FastAPI()
templates = Jinja2Templates(directory="templates")
# DB 연결 함수


def get_conn():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="djsqnr20214",
        database="test2",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )


@app.get("/", response_class=HTMLResponse)
def admin_member(request: Request):
    return templates.TemplateResponse("view.html", {
        "request": request
    })


@app.get("/rider-summary")
async def get_week_summary(
    rider_id: str = Query(...),
    start: str = Query(...),
    end: str = Query(...)
):
    try:
        # 1. 문자열 "20121212" -> datetime.date 객체로 변환
        start_date = datetime.strptime(start, "%Y%m%d").date()
        end_date = datetime.strptime(end, "%Y%m%d").date()

        # 2. 원하는 "YYYY-MM-DD" 문자열로 변환
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

    except ValueError:
        return {"error": "잘못된 날짜 형식입니다. YYYYMMDD 형식이어야 합니다."}
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute("SELECT user_id, name, sum(count) as count, sum(totalA) as totalA, sum(totalB) as totalB,"
                       "sum(totalD) as totalD "
                       "FROM test2.week where start_date >= %s and end_date <= %s and user_id = %s group by user_id, "
                       "name",
                       (start_str, end_str, rider_id))
        results = cursor.fetchone()
        results = convert_row(results)
    conn.close()
    print(results)
    return JSONResponse(content={"status": "success", "data": results})



@app.get("/admin")
def admin_redirect():
    return RedirectResponse(url="/admin-manage")


@app.get("/admin-manage", response_class=HTMLResponse)
def admin_member(request: Request):
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "data": []
    })


@app.get("/admin-member", response_class=HTMLResponse)
def admin_manage(request: Request):
    conn = get_conn()
    members = []
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, name, moto_fee, user_id FROM test2.member")
        results = cursor.fetchall()
        for row in results:
            members.append({
                "id": row["id"],
                "name": row["name"],
                "moto_fee": row["moto_fee"],
                "user_id": row["user_id"]
            })
    conn.close()

    return templates.TemplateResponse("member.html", {
        "request": request,
        "members": members
    })

# 회원 추가


@app.get("/member/add")
def add_member(name: str = Query(..., min_length=1),
               user_id: str = Query(..., min_length=1)):

    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO member (name, user_id) VALUES (%s, %s)", (name, user_id))
        conn.commit()
    conn.close()
    return {"result": "ok"}


class MemberEdit(BaseModel):
    name: str
    moto_fee: int
    # 필요한 다른 필드들도 추가 가능


@app.put("/member/edit/{mid}")
def edit_member(
    mid: int = Path(...),
    data: MemberEdit = Body(...)
):
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE test2.member SET moto_fee = %s WHERE id = %s and name = %s",
            (data.moto_fee, mid, data.name,)
        )
        conn.commit()
    conn.close()
    return {"result": "ok"}


@app.get("/admin-manage", response_class=HTMLResponse)
async def form_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


async def fetch_moto_fees():
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute("SELECT name, moto_fee FROM test2.member")
        result = cursor.fetchall()
    conn.close()
    return result  # {라이더명: moto_fee}


@app.post("/upload")
async def upload_excel(
    file1: Optional[UploadFile] = File(None),
    file2: Optional[UploadFile] = File(None)
):
    if not file1 and not file2:
        return JSONResponse(status_code=400, content={"status": "error", "message": "file1 또는 file2 중 하나는 반드시 필요합니다."})

    try:
        result = {}

        # file1 처리 (배달처리비)
        if file1:
            file_bytes = await file1.read()
            decrypted = io.BytesIO()
            office_file = msoffcrypto.OfficeFile(io.BytesIO(file_bytes))
            office_file.load_key(password="Bz6206")
            office_file.decrypt(decrypted)
            decrypted.seek(0)
            df = pd.read_excel(decrypted, engine="openpyxl")

            if not {'라이더명', '배달처리비', '운행일'}.issubset(df.columns):
                return JSONResponse(status_code=400, content={"status": "error", "message": "file1 데이터가 일치하지 않습니다."})
            df['운행일'] = df['운행일'].astype(str)

            grouped = df.groupby(['라이더명', '운행일'])['배달처리비'].sum().reset_index()

            for _, row in grouped.iterrows():
                rider = row['라이더명']
                if rider not in result:
                    result[rider] = {
                        "총합계": 0,
                        "기록": []
                    }
                result[rider]["기록"].append({
                    "운행일": row["운행일"],
                    "배달처리비": int(row["배달처리비"])
                })
                result[rider]["총합계"] += int(row["배달처리비"])

        # file2 처리 (보험료)
        if file2:
            file2_bytes = await file2.read()
            decrypted2 = io.BytesIO()
            office_file2 = msoffcrypto.OfficeFile(io.BytesIO(file2_bytes))
            office_file2.load_key(password="Bz6206!6206")
            office_file2.decrypt(decrypted2)
            decrypted2.seek(0)
            df2 = pd.read_excel(decrypted2, engine="openpyxl")

            if not {'운행일', '이름', '보험료 발생금액(원)'}.issubset(df2.columns):
                return JSONResponse(status_code=400, content={"status": "error", "message": "file2 데이터가 일치하지 않습니다."})
            df2['운행일'] = df2['운행일'].astype(str)

            insurance_data = df2.groupby(['이름', '운행일'])['보험료 발생금액(원)'].sum().reset_index()

            for _, row in insurance_data.iterrows():
                rider = row['이름']
                운행일 = row['운행일']
                보험료 = int(row['보험료 발생금액(원)'])

                if rider not in result:
                    result[rider] = {
                        "총합계": 0,
                        "기록": []
                    }

                records = result[rider]["기록"]
                rec = next((r for r in records if r["운행일"] == 운행일), None)
                if rec:
                    rec["보험료 발생금액(원)"] = 보험료
                else:
                    result[rider]["기록"].append({
                        "운행일": 운행일,
                        "배달처리비": 0,
                        "보험료 발생금액(원)": 보험료
                    })

        # file2가 없으면 보험료 0원 추가
        if file1 and not file2:
            for rider in result:
                for rec in result[rider]["기록"]:
                    rec["보험료 발생금액(원)"] = 0

        # file1이 없으면 배달처리비 0원 추가
        if file2 and not file1:
            for rider in result:
                for rec in result[rider]["기록"]:
                    rec["배달처리비"] = 0

        # 오토바이 요금 추가
        moto_fee_list = await fetch_moto_fees()
        moto_fee_map = {entry['name']: entry['moto_fee'] for entry in moto_fee_list}

        for rider in result:
            result[rider]["moto_fee"] = moto_fee_map.get(rider, 0)

        return {
            "status": "success",
            "data": result
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.get("/admin-week", response_class=HTMLResponse)
async def form_page2(request: Request):
    return templates.TemplateResponse("week.html", {"request": request})


@app.get("/admin-week-plus", response_class=HTMLResponse)
async def form_page3(request: Request):
    return templates.TemplateResponse("weekplus.html", {"request": request})


def parse_amount(value):
    if pd.isna(value) or str(value).strip() == '-':
        return 0
    try:
        return int(str(value).replace(',', '').strip())
    except:
        return 0


@app.post("/upload/week")
async def form_week(file1: UploadFile = File(...)):
    if not file1:
        return JSONResponse(status_code=400, content={"status": "error", "message": "file1 반드시 필요합니다."})

    filename = file1.filename
    match = re.match(r"^(\d{8})~(\d{8})", filename)
    if not match:
        return JSONResponse(status_code=400, content={"status": "error", "message": "파일명은 'YYYYMMDD~YYYYMMDD' 형식으로 시작해야 합니다."})

    start_date, end_date = match.group(1), match.group(2)

    password = "8188703715"
    sheet_name = "을지_협력사 소속 라이더 정산 확인용"
    extra_fee_sheet = "추가배달료"

    try:
        encrypted_file = msoffcrypto.OfficeFile(file1.file)
        encrypted_file.load_key(password=password)

        decrypted = io.BytesIO()
        encrypted_file.decrypt(decrypted)

        df = pd.read_excel(decrypted, sheet_name=sheet_name, header=None)
        start_row = 19  # 20번째 행부터

        result = []
        for i in range(start_row, len(df)):
            user_id = df.iloc[i, 1]
            name = df.iloc[i, 2]
            count = df.iloc[i, 3]
            totalA = df.iloc[i, 4]
            totalD = df.iloc[i, 7]

            if pd.isna(user_id) and pd.isna(name) and pd.isna(count):
                continue

            result.append({
                "user_id": str(user_id).strip(),
                "name": str(name).strip(),
                "count": int(count) if pd.notna(count) else 0,
                "totalA": parse_amount(totalA),
                "totalD": parse_amount(totalD)
            })

        # 추가배달료 시트 처리
        df_fee = pd.read_excel(decrypted, sheet_name=extra_fee_sheet, header=None)
        fee_start_row = 10  # 11행부터 (0-based)

        fee_dict = {}
        for i in range(fee_start_row, len(df_fee)):
            name_fee = df_fee.iloc[i, 2]  # C열: 이름
            amount_fee = df_fee.iloc[i, 3]  # D열: 금액
            reason = df_fee.iloc[i, 5]      # F열: 사유

            if pd.isna(name_fee) or pd.isna(amount_fee):
                continue
            if isinstance(reason, str) and reason.startswith("기피"):
                continue

            amount_fee_parsed = parse_amount(amount_fee)
            name_key = str(name_fee).strip()
            fee_dict[name_key] = fee_dict.get(name_key, 0) + amount_fee_parsed

        for item in result:
            item["totalB"] = fee_dict.get(item["name"], 0)

        # DB insert
        conn = get_conn()
        with conn.cursor() as cursor:
            for item in result:
                cursor.execute(
                    "INSERT INTO week (user_id, name, start_date, end_date, count, totalA, totalB, totalD) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        item["user_id"],
                        item["name"],
                        start_date,
                        end_date,
                        item["count"],
                        item["totalA"],
                        item["totalB"],
                        item["totalD"],
                    )
                )
            conn.commit()
        conn.close()

        return {
            "status": "success",
            "start_date": start_date,
            "end_date": end_date,
            "data": result
        }

    except Exception as e:
        print(e)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.post("/upload/week/plus")
async def form_week(
        file1: UploadFile = File(...)
):
    if not file1:
        return JSONResponse(status_code=400, content={"status": "error", "message": "file1 반드시 필요합니다."})
    result = []
    return {
        "status": "success",
        "data": result
    }


@app.get("/week-summary")
async def get_week_summary(start: str = Query(...), end: str = Query(...)):
    try:
        # 1. 문자열 "20121212" -> datetime.date 객체로 변환
        start_date = datetime.strptime(start, "%Y%m%d").date()
        end_date = datetime.strptime(end, "%Y%m%d").date()

        # 2. 원하는 "YYYY-MM-DD" 문자열로 변환
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

    except ValueError:
        return {"error": "잘못된 날짜 형식입니다. YYYYMMDD 형식이어야 합니다."}
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute("SELECT user_id, name, sum(count) as count, sum(totalA) as totalA, sum(totalB) as totalB,"
                       "sum(totalD) as totalD "
                       "FROM test2.week where start_date >= %s and end_date <= %s group by user_id, name",
                       (start_str, end_str))
        results = cursor.fetchall()
        results = [convert_row(row) for row in results]
    conn.close()
    return JSONResponse(content={"status": "success", "data": results})


def convert_row(row):
    return {k: (int(v) if isinstance(v, Decimal) and v % 1 == 0 else float(v) if isinstance(v, Decimal) else v)
            for k, v in row.items()}
