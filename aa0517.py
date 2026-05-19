import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
import time
import re
import xml.etree.ElementTree as ET

# 스트림릿 와이드 레이아웃 및 페이지 설정 가동
st.set_page_config(page_title="하이모바일 주식 매니저 (최종 완결본)", layout="wide")

# ==========================================
# 🔒 [보안 강화] 구글 API 키 자동 주입 (Secrets 연동)
# ==========================================
# 더 이상 코드나 화면상에 키를 직접 노출하지 않고, Streamlit Secrets에서만 비공개로 안전하게 호출합니다.
GEMINI_API_KEY = ""

if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# 최초 실행 및 부족한 개수를 메워줄 백업용 마스터 리스트 (대한민국 대표 우량주 50선)
BACKUP_50_STOCKS = (
    "삼성전자:005930, SK하이닉스:000660, 한미반도체:042700, 리노공업:058470, 이오테크닉스:039030, "
    "HPSP:403870, 가온칩스:454840, 오픈에지테크놀로지:394280, 에이직랜드:445090, 주성엔지니어링:036930, "
    "현대차:005380, 기아:000270, 현대로템:064350, 현대모비스:012330, HL만도:204320, "
    "HD현대인프라코어:042670, 한국항공우주:047810, 한화에어로스페이스:012450, LIG넥스원:079550, 두산로보틱스:454910, "
    "레인보우로보틱스:277810, 뉴로메카:348340, LG에너지솔루션:373220, 삼성SDI:006400, 포스코퓨처엠:003670, "
    "에코프로비엠:247540, 엘앤에프:066970, HD현대일렉트릭:043200, 효성중공업:298040, LS일렉트릭:010120, "
    "두산에너빌리티:034020, 한화솔루션:009830, 씨에스윈드:112610, 삼성바이오로직스:207940, 셀트리온:068270, "
    "유한양행:000100, 알테오젠:196170, 리그켐바이오:141080, 에이비엘바이오:298380, 휴젤:145020, "
    "메디톡스:086900, 한미약품:128940, SK바이오팜:326030, KB금융:105560, 신한지주:055550, "
    "하나금융지주:086790, 메리츠금융지주:138040, 삼성물산:028260, SK:034730, POSCO홀딩스:005490"
)

# 최초 실행 시 화면에 예시 가이드라인용으로만 보여줄 기본 5개 종목
INITIAL_5_STOCKS = "삼성전자:005930, SK하이닉스:000660, 현대차:005380, 기아:000270, 현대로템:064350"

if 'raw_input_area' not in st.session_state:
    st.session_state['raw_input_area'] = INITIAL_5_STOCKS
if 'final_success' not in st.session_state:
    st.session_state.final_success = []
if 'final_warning' not in st.session_state:
    st.session_state.final_warning = []
if 'final_info' not in st.session_state:
    st.session_state.final_info = []
if 'final_failed' not in st.session_state:
    st.session_state.final_failed = []
if 'run_analysis' not in st.session_state:
    st.session_state.run_analysis = False
if 'api_error_msg' not in st.session_state:
    st.session_state.api_error_msg = ""
if 'clicked_stock' not in st.session_state:
    st.session_state.clicked_stock = None

def get_naver_data(code, count=90):
    """네이버 금융 공식 일별 차트 XML 피드에서 실시간 데이터프레임을 완벽히 파싱합니다."""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1',
        'Referer': f'https://m.stock.naver.com/domestic/stock/{code}/total'
    }
    try:
        response = requests.get(url, headers=headers, timeout=3.0)
        root = ET.fromstring(response.text)
        parsed_data = []
        for item in root.findall('.//item'):
            data_row = item.get('data').split('|')
            parsed_data.append(data_row)
        if not parsed_data:
            return pd.DataFrame()
        
        df = pd.DataFrame(parsed_data, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d', errors='coerce')
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna().reset_index(drop=True)
        return df
    except Exception as e:
        return pd.DataFrame()

st.markdown("### 🔓 필터가 완화된 3단계 복합 판단 로직")
lead_col1, lead_col2, lead_col3 = st.columns(3)
with lead_col1:
    st.markdown("<div style='background-color:#e8f5e9; padding:12px; border-radius:10px; border-left:5px solid #2e7d32;'><b>📈 1단계: 압축 최적 매수 (전면 개방)</b><br><span style='font-size:12px;'>정배열 상태라면 대부분 포착<br><b>이격도 115%까지 전면 확대 / RSI 85까지 초과열 허용</b></span></div>", unsafe_allow_html=True)
with lead_col2:
    st.markdown("<div style='background-color:#fffde7; padding:12px; border-radius:10px; border-left:5px solid #fbc02d;'><b>⚠️ 2단계: 초고공 급등 주도주</b><br><span style='font-size:12px;'>정배열 및 추세가 멈추지 않고 폭발하여<br>단기 이격도가 115%마저 초과해 버린 상투 위험 구역</span></div>", unsafe_allow_html=True)
with lead_col3:
    st.markdown("<div style='background-color:#efebe9; padding:12px; border-radius:10px; border-left:5px solid #4e342e;'><b>💤 3단계: 추세 관망</b><br><span style='font-size:12px;'>역배열 상태이거나 단기 하방 추세가 진행 중인 관망 구역</span></div>", unsafe_allow_html=True)

st.markdown("---")

if st.session_state.api_error_msg:
    st.error("🚨 [구글 API 인증 및 네트워크 통신 상태 에러 확인]")
    st.code(st.session_state.api_error_msg, language="json")
    if st.button("❌ 에러 창 닫기 및 초기화"):
        st.session_state.api_error_msg = ""
        st.rerun()

st.markdown("### 🛠️ 종목 리스트 제어 센터")
ai_col1, ai_col2 = st.columns([0.3, 0.7])

with ai_col1:
    st.write("")
    if st.button("🪄 Gemini AI 유망 종목 50개 자동 추출", use_container_width=True, type="primary"):
        # Secrets에 키가 아예 설정되지 않은 상황 방어
        if not GEMINI_API_KEY or GEMINI_API_KEY.strip() == "":
            st.error("🔒 구글 API 키가 설정되지 않았습니다. Streamlit Secrets 대시보드에 'GEMINI_API_KEY' 항목으로 키를 입력해 주세요!")
        else:
            status_container = st.empty()
            with status_container.container():
                st.info("🤖 최신 안전 엔진이 종목을 연산 중입니다. 통신 방어 로직 가동 중...")
                
            st.session_state.api_error_msg = "" 
            url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            headers = {'Content-Type': 'application/json'}
            prompt = (
                "국내 주식 시장에서 현재 시점 기준으로 가장 유망해 보이는 핵심 우량 종목을 '중복 없이 정확히 50개' 선정해라. "
                "반드시 서론, 설명, 마크다운 기호 다 빼고 오직 '종목명:6자리코드'의 형태로만 작성하고, "
                "각 종목들은 쉼표(,)로만 연결해서 단 한 줄의 텍스트 스트링으로 반환해라. 예: 삼성전자:005930,SK하이닉스:000660"
            )
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            
            success_communication = False
            response = None
            
            # 구글 서버 통신 지연에 대응한 3단계 자동 재시도 로직
            for attempt in range(1, 4):
                try:
                    status_container.warning(f"⏳ [통신 시도 {attempt}/3단계] 구글 인공지능 망 연결 중...")
                    response = requests.post(url, headers=headers, json=data, timeout=60)
                    if response.status_code == 200:
                        success_communication = True
                        break
                    elif response.status_code == 429:
                        time.sleep(3)
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                    time.sleep(2)
                    continue
            
            status_container.empty()
            
            # 통신 실패 시 가짜 백업 리스트를 로드하지 않고 투명하게 예외를 화면에 표시합니다.
            if success_communication and response is not None:
                try:
                    text_result = response.json()['candidates'][0]['content']['parts'][0]['text']
                    text_result = text_result.replace("```", "").replace("`", "")
                    cleaned_result = text_result.strip().replace("\n", "").replace(" ", "")
                    
                    if len(cleaned_result) > 20:
                        st.session_state['raw_input_area'] = cleaned_result
                        st.success("🤖 AI 추천 리스트 주입 성공!")
                        st.session_state.api_error_msg = ""
                        st.session_state.clicked_stock = None
                except Exception as parse_err:
                    st.session_state.api_error_msg = f"데이터 추출 파싱 실패: {parse_err}\n원본: {response.text}"
            else:
                if response is not None:
                    st.session_state.api_error_msg = f"구글 서버 최종 거부\n상태 코드: {response.status_code}\n내용: {response.text}"
                else:
                    st.session_state.api_error_msg = "국제 인터넷망 지연 또는 구글 API 키 유출 차단 상태입니다. API 키 값을 재점검하십시오."
            
            st.rerun()

with ai_col2:
    user_stocks_input = st.text_area("현재 분석 대상 종목 필드", value=st.session_state['raw_input_area'], height=80, key="raw_input_field")
    if user_stocks_input != st.session_state['raw_input_area']:
        st.session_state['raw_input_area'] = user_stocks_input

# 동기화 및 2단계 초정밀 파싱 파이프라인
current_stocks_map = {}
target_text = st.session_state['raw_input_area'] if st.session_state['raw_input_area'] else ""

# 어떤 기호(공백, 괄호, 줄바꿈)가 섞여 있어도 종목명과 6자리 코드를 완벽하게 발라내는 정규식 엔진
matches = re.findall(r'([가-힣a-zA-Z0-9_]+)\s*[:\(\[-]?\s*(\d{6})', target_text)

for name_part, code_part in matches:
    # 혹시나 포함되어 있을지 모를 순번 제거 (예: "1.삼성전자" -> "삼성전자")
    clean_name = re.sub(r'^\d+[\.\s\-]*', '', name_part)
    clean_name = re.sub(r'[^a-zA-Z0-9가-힣]', '', clean_name).strip()
    clean_code = code_part.strip()
    
    if clean_name and len(clean_code) == 6:
        current_stocks_map[clean_name] = clean_code

# 🛡️ [핵심 보완] AI가 출력한 종목이 50개 미만일 때 부족한 양을 백업 종목으로 자동 채움
backup_map = {}
for item in BACKUP_50_STOCKS.split(','):
    if ":" in item:
        parts = item.split(":")
        b_name = re.sub(r'[^a-zA-Z0-9가-힣]', '', parts[0]).strip()
        b_code = ''.join(filter(str.isdigit, parts[1]))[:6]
        if b_name and len(b_code) == 6:
            backup_map[b_name] = b_code

if len(current_stocks_map) > 5 and len(current_stocks_map) < 50:
    for b_name, b_code in backup_map.items():
        if len(current_stocks_map) >= 50:
            break
        if b_name not in current_stocks_map and b_code not in current_stocks_map.values():
            current_stocks_map[b_name] = b_code

if current_stocks_map:
    st.info(f"📋 시스템 상태: **{len(current_stocks_map)}개** 종목 실시간 연동 완료 (50개 풀 자동 조율 완료)")

# ==========================================
# 🚀 스크리닝 엔진 (가상 백업 모크 데이터 전면 폐기)
# ==========================================
if st.button("🚀 맹점 전면 개방형 고성능 스크리닝 시작", use_container_width=True):
    if not current_stocks_map:
        st.error("오류: 현재 파싱된 종목이 전혀 없습니다.")
    else:
        suc_temp, war_temp, inf_temp, fail_temp = [], [], [], []
        progress_bar = st.progress(0)
        total = len(current_stocks_map)
        
        for idx, (name, code) in enumerate(current_stocks_map.items()):
            progress_bar.progress((idx + 1) / total)
            
            try:
                # 네이버 차트 XML 수집 엔진 실행 (수치 연산 및 분석용)
                df = get_naver_data(code)
                
                if len(df) >= 60:
                    df['MA20'] = df['Close'].rolling(window=20).mean()
                    df['MA60'] = df['Close'].rolling(window=60).mean()
                    
                    delta = df['Close'].diff()
                    up, down = delta.clip(lower=0), -delta.clip(upper=0)
                    ema_up = up.ewm(com=13, adjust=False).mean()
                    ema_down = down.ewm(com=13, adjust=False).mean()
                    df['RSI'] = 100 - (100 / (1 + (ema_up / ema_down)))
                    df['Vol_MA5'] = df['Volume'].shift(1).rolling(window=5).mean()
                    
                    curr_close = int(df['Close'].iloc[-1])
                    ma20 = float(df['MA20'].iloc[-1])
                    ma60 = float(df['MA60'].iloc[-1])
                    disparity_20 = (curr_close / ma20) * 100
                    
                    rsi_val = round(float(df['RSI'].iloc[-1]), 1) if not pd.isna(df['RSI'].iloc[-1]) else 50.0
                    curr_vol = float(df['Volume'].iloc[-1])
                    vol_ma5 = float(df['Vol_MA5'].iloc[-1]) if not pd.isna(df['Vol_MA5'].iloc[-1]) else curr_vol
                    vol_ratio = curr_vol / vol_ma5 if vol_ma5 > 0 else 1.0
                    
                    stock_info = {
                        "종목명": name, "종목코드": code, "현재가": f"{curr_close:,}원", 
                        "RSI": rsi_val, "이격도(20일)": f"{disparity_20:.1f}%"
                    }
                    
                    # 수문장 개방형 조건문 대입
                    if (curr_close > ma20 > ma60) and (disparity_20 <= 115.0) and (35 <= rsi_val <= 85) and (vol_ratio >= 0.3):
                        suc_temp.append(stock_info)
                    elif (curr_close > ma20 > ma60):
                        war_temp.append(stock_info)
                    else:
                        inf_temp.append(stock_info)
                else:
                    raise Exception("데이터 부족")
            except Exception as e:
                # 통신이나 계산 실패 시 가상 데이터를 임의 주입하지 않고, 실패 리스트에 정확히 격리 기록합니다.
                fail_temp.append({
                    "종목명": name, "종목코드": code, "상태": "데이터 연동실패", "사유": str(e)
                })
                
            time.sleep(0.01)
            
        progress_bar.empty()
        st.session_state.final_success = suc_temp
        st.session_state.final_warning = war_temp
        st.session_state.final_info = inf_temp
        st.session_state.final_failed = fail_temp
        st.session_state.run_analysis = True
        st.session_state.clicked_stock = None
        st.rerun()

# ==========================================
# 📊 테이블 출력 구역
# ==========================================
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("<h4 style='color:#2e7d32; border-bottom:2px solid #2e7d32; padding-bottom:5px;'>📈 1단계: 압축 최적 매수</h4>", unsafe_allow_html=True)
    if st.session_state.run_analysis:
        if st.session_state.final_success:
            df_suc = pd.DataFrame(st.session_state.final_success)
            event_suc = st.dataframe(df_suc, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
            if event_suc and "selection" in event_suc and "rows" in event_suc["selection"] and event_suc["selection"]["rows"]:
                st.session_state.clicked_stock = st.session_state.final_success[event_suc["selection"]["rows"][0]]
        else:
            st.info("조건 만족 주식이 없습니다.")

with col2:
    st.markdown("<h4 style='color:#fbc02d; border-bottom:2px solid #fbc02d; padding-bottom:5px;'>⚠️ 2단계: 고과열 돌파형 (진입 조율)</h4>", unsafe_allow_html=True)
    if st.session_state.run_analysis:
        if st.session_state.final_warning:
            df_war = pd.DataFrame(st.session_state.final_warning)
            event_war = st.dataframe(df_war, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
            if event_war and "selection" in event_war and "rows" in event_war["selection"] and event_war["selection"]["rows"]:
                st.session_state.clicked_stock = st.session_state.final_warning[event_war["selection"]["rows"][0]]
        else:
            st.info("조건 만족 주식이 없습니다.")

with col3:
    st.markdown("<h4 style='color:#4e342e; border-bottom:2px solid #4e342e; padding-bottom:5px;'>💤 3단계: 추세 관망 권장</h4>", unsafe_allow_html=True)
    if st.session_state.run_analysis:
        if st.session_state.final_info:
            df_inf = pd.DataFrame(st.session_state.final_info)
            event_inf = st.dataframe(df_inf, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
            if event_inf and "selection" in event_inf and "rows" in event_inf["selection"] and event_inf["selection"]["rows"]:
                st.session_state.clicked_stock = st.session_state.final_info[event_inf["selection"]["rows"][0]]
        else:
            st.info("조건 만족 주식이 없습니다.")

# ==========================================
# 🛑 분석 실패 종목 별도 표시 구역 (대표님 투명성 확보 목적)
# ==========================================
if st.session_state.run_analysis and st.session_state.final_failed:
    st.markdown("---")
    st.warning("⚠️ **실시간 데이터 수집 실패 종목 리스트**")
    st.caption("해당 종목들은 임의의 백업 가상 데이터 대신 무결성을 위해 계산에서 제외처리 되었습니다.")
    df_failed = pd.DataFrame(st.session_state.final_failed)
    st.dataframe(df_failed, use_container_width=True, hide_index=True)

# ==========================================
# 🖥️ 네이버 모바일 웹 우회형 즉시 표출 차트 엔진
# ==========================================
if st.session_state.clicked_stock:
    st.markdown("---")
    s_name = st.session_state.clicked_stock["종목명"]
    s_code = st.session_state.clicked_stock["종목코드"]
    
    st.markdown(f"### 📊 [{s_name} : {s_code}] 실시간 종합 차트 (화면 내 즉시 표출)")
    
    naver_mobile_chart_url = f"https://m.stock.naver.com/domestic/stock/{s_code}/total"
    
    naver_chart_html = f"""
    <div style="width: 100%; height: 700px; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0;">
      <iframe src="{naver_mobile_chart_url}" 
              style="width: 100%; height: 100%; border: none; margin: 0; padding: 0;" 
              allowfullscreen></iframe>
    </div>
    """
    st.components.v1.html(naver_chart_html, height=720)
else:
    if st.session_state.run_analysis:
        st.markdown("---")
        st.info("💡 위의 표에서 종목 줄(Row)을 툭 클릭하시면, 화면 이동 없이 하단 구역에 네이버 실시간 종합 차트가 즉시 펼쳐집니다.")
