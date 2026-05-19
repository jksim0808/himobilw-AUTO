import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
from datetime import datetime
import time

# --- 1. 한국투자증권 API 통신 클래스 (토큰 세션 저장형) ---
class KoreaInvestmentAPI:
    def __init__(self, app_key, app_secret, mock_flag=True):
        if mock_flag:
            self.base_url = "https://openapivts.koreainvestment.com:29443" # 모의투자
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"    # 실운영
            
        self.app_key = app_key
        self.app_secret = app_secret

    def get_access_token(self):
        """OAuth2.0 접근 토큰(Access Token) 발급 - 세션 상태를 확인하여 1분당 1회 제한 우회"""
        if "api_access_token" in st.session_state and st.session_state.api_access_token:
            return st.session_state.api_access_token

        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                token = response.json().get("access_token")
                st.session_state.api_access_token = token
                return token
            else:
                error_msg = response.json().get('error_description', '알 수 없는 에러')
                st.sidebar.error(f"토큰 발급 실패: {error_msg}")
                return None
        except Exception as e:
            st.sidebar.error(f"한투 서버 연결 실패: {e}")
            return None

    def get_realtime_price(self, ticker):
        """주식현재가 일자별/시간별 체결 데이터 조회 (TR: FHKST01010100)"""
        access_token = self.get_access_token()
        if not access_token:
            return None

        url = f"{self.base_url}/uapi/domestic-stock/v1/quoting/inquire-price"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100"
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                res_data = response.json().get("output", {})
                return {
                    "Close": float(res_data.get("stck_prpr", 0)),
                    "High": float(res_data.get("stck_hgpr", 0)),
                    "Low": float(res_data.get("stck_lwpr", 0)),
                    "Volume": float(res_data.get("accl_tr_vol", 0)) # 당일 누적 거래량
                }
            else:
                st.error(f"시세 조회 오류: {response.text}")
                return None
        except Exception as e:
            st.error(f"API 통신 오류: {e}")
            return None

# --- 2. 퀀트 단타 지표 연산 알고리즘 (누적 왜곡 방어 보정) ---
def calculate_indicators(df):
    if len(df) < 2:
        return df
    
    # 🛡️ 당일 누적 거래량(Volume)의 차분(Diff)을 구하여 해당 주기 '순수 거래량' 산출
    df['Pure_Volume'] = df['Volume'].diff()
    df['Pure_Volume'].iloc[0] = df['Volume'].iloc[0]
    df['Pure_Volume'] = df['Pure_Volume'].clip(lower=0)

    # 보정된 순수 거래량 기반 VWAP 연산
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    df['Price_Vol'] = typical_price * df['Pure_Volume']
    df['VWAP'] = df['Price_Vol'].cumsum() / (df['Pure_Volume'].cumsum() + 1e-9)
    
    # 단기 RSI 연산 (5주기)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=min(5, len(df)-1), min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=min(5, len(df)-1), min_periods=1).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    
    # 직전고가 저항선 및 거래량 이동평균 산출
    df['Local_High'] = df['High'].shift(1).rolling(window=min(3, len(df)-1), min_periods=1).max()
    df['Vol_MA'] = df['Pure_Volume'].shift(1).rolling(window=min(3, len(df)-1), min_periods=1).mean()
    return df

# --- 3. 웹 UI 화면 구성 ---
st.set_page_config(page_title="한투 API 실시간 단타기", layout="wide")

st.title("🏹 한국투자증권 Open API 실시간 단타 예측 대시보드")
st.caption("누적 거래량 VWAP 왜곡 방지 보정 로직 + 네이버 실시간 모바일 차트 화면 내 상시 표출 시스템")

# 세션 상태 초기화
if "stock_history" not in st.session_state:
    st.session_state.stock_history = pd.DataFrame()
if "last_ticker" not in st.session_state:
    st.session_state.last_ticker = ""
if "api_access_token" not in st.session_state:
    st.session_state.api_access_token = None

# 사이드바 설정
st.sidebar.header("🔑 한투 Open API 인증 정보")
app_key = st.sidebar.text_input("App Key", type="password")
app_secret = st.sidebar.text_input("App Secret", type="password")
server_type = st.sidebar.radio("서버 선택", ["모의투자 서버", "실운영 서버"])
mock_flag = True if server_type == "모의투자 서버" else False

if st.sidebar.button("🔑 토큰 초기화 (재발급 필요시)"):
    st.session_state.api_access_token = None
    st.sidebar.success("토큰이 초기화되었습니다.")

st.sidebar.markdown("---")
st.sidebar.header("🔍 종목 설정")
ticker_input = st.sidebar.text_input("종목코드 입력 (6자리)", value="005930")

if ticker_input != st.session_state.last_ticker:
    st.session_state.stock_history = pd.DataFrame()
    st.session_state.last_ticker = ticker_input

st.sidebar.markdown("---")
run_btn = st.sidebar.button("🔄 실시간 시세 갱신 및 타점 연산", use_container_width=True, type="primary")

# 메인 제어 파이프라인
if run_btn:
    if app_key and app_secret:
        api = KoreaInvestmentAPI(app_key, app_secret, mock_flag=mock_flag)
        tick_data = api.get_realtime_price(ticker_input)
        
        if tick_data and tick_data["Close"] > 0:
            new_row = pd.DataFrame([{
                "Close": tick_data["Close"],
                "High": tick_data["High"],
                "Low": tick_data["Low"],
                "Volume": tick_data["Volume"]
            }], index=[pd.to_datetime(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))])
            
            st.session_state.stock_history = pd.concat([st.session_state.stock_history, new_row]).tail(30)
            
            df = calculate_indicators(st.session_state.stock_history.copy())
            latest = df.iloc[-1]
            
            prev_close = df['Close'].iloc[-2] if len(df) > 1 else latest['Close']
            prev_local_high = latest['Local_High'] if not pd.isna(latest['Local_High']) else latest['Close']
            prev_vol_ma = latest['Vol_MA'] if not pd.isna(latest['Vol_MA']) else latest['Pure_Volume']
            
            # 단타 스캘핑 필터 최적화 조율 (순수 체결 거래량이 직전 평균 대비 1.5배 돌파 시 장대수급 인정)
            cond_breakout = latest['Close'] >= prev_local_high
            st_above_vwap = latest['Close'] > latest['VWAP']
            cond_volume = latest['Pure_Volume'] > (prev_vol_ma * 1.5)
            
            is_buy_signal = cond_breakout and st_above_vwap and cond_volume
            
            # 상단 핵심 현황 스코어보드
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(label="현재 체결가", value=f"{int(latest['Close']):,} 원", delta=f"{int(latest['Close'] - prev_close):,} 원")
            with col2:
                st.metric(label="당일 전체 누적 거래량", value=f"{int(latest['Volume']):,} 주")
            with col3:
                st.metric(label="단기 저항선 (직전고가)", value=f"{int(prev_local_high):,} 원")
            with col4:
                st.metric(label="단기 RSI", value=f"{int(latest['RSI'])}" if not pd.isna(latest['RSI']) else "계산중")
                
            st.markdown("---")
            
            if is_buy_signal:
                st.error(f"🔥 [한투 API 매수 타점 포착] {ticker_input} 종목이 거래량 폭발과 함께 저항선을 강하게 뚫었습니다!")
                st.balloons()
            else:
                st.success(f"🟢 [한투 API 실시간 감시 중] 조건 충족 대기 중 (정상 연동 가동률 100%)")
                
            # 데이터 대시보드 시각화 구역
            col_chart, col_table = st.columns([0.6, 0.4])
            with col_chart:
                st.subheader("📊 주가 및 단기 수급선(VWAP) 추이 분석")
                chart_data = df[['Close', 'VWAP']]
                chart_data.columns = ['현재가', '수급평균선(VWAP)']
                st.line_chart(chart_data, use_container_width=True)
            with col_table:
                st.subheader("📋 최신 실시간 데이터 히스토리")
                st.dataframe(df.tail(5)[['Close', 'Pure_Volume', 'VWAP', 'RSI']], use_container_width=True)
    else:
        st.sidebar.warning("⚠️ App Key와 App Secret을 입력해 주세요.")

# ==========================================
# 🖥️ [보안 해제 완료] 네이버 금융 모바일 실시간 종합 전광판 상시 노출 구역
# ==========================================
st.markdown("---")
st.markdown(f"### 📱 실시간 호가창 및 캔들 차트 검증 모니터")

naver_mobile_url = f"https://m.stock.naver.com/domestic/stock/{ticker_input}/total"

chart_html = f"""
<div style="width: 100%; height: 650px; border-radius: 12px; overflow: hidden; border: 1px solid #e0e0e0; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
  <iframe src="{naver_mobile_url}" 
          style="width: 100%; height: 100%; border: none; margin: 0; padding: 0;" 
          allowfullscreen></iframe>
    </div>
    """
st.components.v1.html(chart_html, height=670)
