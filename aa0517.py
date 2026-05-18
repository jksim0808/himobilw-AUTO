import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
from datetime import datetime

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
        # [핵심 보완] 이미 메모리에 살아있는 토큰이 있다면 한투 서버에 요청하지 않고 그대로 사용
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
                # 발급받은 토큰을 Streamlit 메모리(Session State)에 영구 저장
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
        # 메모리 또는 서버에서 토큰 가져오기
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
                    "Volume": float(res_data.get("accl_tr_vol", 0))
                }
            else:
                st.error(f"시세 조회 오류: {response.text}")
                return None
        except Exception as e:
            st.error(f"API 통신 오류: {e}")
            return None

# --- 2. 퀀트 단타 지표 연산 알고리즘 ---
def calculate_indicators(df):
    if len(df) < 2:
        return df
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    df['Price_Vol'] = typical_price * df['Volume']
    df['VWAP'] = df['Price_Vol'].cumsum() / (df['Volume'].cumsum() + 1e-9)
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=min(5, len(df)-1), min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=min(5, len(df)-1), min_periods=1).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    
    df['Local_High'] = df['High'].shift(1).rolling(window=min(3, len(df)-1), min_periods=1).max()
    df['Vol_MA'] = df['Volume'].shift(1).rolling(window=min(3, len(df)-1), min_periods=1).mean()
    return df

# --- 3. 웹 UI 화면 구성 ---
st.set_page_config(page_title="한투 API 실시간 단타기", layout="wide")

st.title("🏹 한국투자증권 Open API 실시간 단타 예측 대시보드")
st.markdown("토큰 세션 저장 로직이 적용되어 안정적인 조회가 가능합니다.")

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

# [추가] 토큰이 꼬였을 때 강제로 새로 발급받을 수 있는 비상 버튼
if st.sidebar.button("🔑 토큰 초기화 (재발급 필요시)"):
    st.session_state.api_access_token = None
    st.sidebar.success("토큰이 초기화되었습니다. 다음 조회 시 새로 발급합니다.")

st.sidebar.markdown("---")
st.sidebar.header("🔍 종목 설정")
ticker_input = st.sidebar.text_input("종목코드 입력 (6자리 + Enter)", value="005930")

if ticker_input != st.session_state.last_ticker:
    st.session_state.stock_history = pd.DataFrame()
    st.session_state.last_ticker = ticker_input

if st.sidebar.button("🔄 실시간 시세 갱신 및 타점 연산"):
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
            prev_vol_ma = latest['Vol_MA'] if not pd.isna(latest['Vol_MA']) else latest['Volume']
            
            cond_breakout = latest['Close'] >= prev_local_high
            st_above_vwap = latest['Close'] > latest['VWAP']
            cond_volume = latest['Volume'] > (prev_vol_ma * 1.05)
            
            is_buy_signal = cond_breakout and st_above_vwap and cond_volume
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(label=f"현재 체결가", value=f"{int(latest['Close']):,} 원", delta=f"{int(latest['Close'] - prev_close):,} 원")
            with col2:
                st.metric(label="당일 누적 거래량", value=f"{int(latest['Volume']):,} 주")
            with col3:
                st.metric(label="단기 저항선 (직전고가)", value=f"{int(prev_local_high):,} 원")
            with col4:
                st.metric(label="RSI (단기 심리지표)", value=f"{int(latest['RSI'])}" if not pd.isna(latest['RSI']) else "계산중")
                
            st.markdown("---")
            
            if is_buy_signal:
                st.error(f"🔥 [한투 API 매수 타점] {ticker_input} 종목이 저항선을 돌파했습니다!")
                st.balloons()
            else:
                st.success(f"🟢 [한투 API 정상 연동] 현재 {ticker_input} 종목 실시간 추적 중.")
                
            st.subheader("📊 주가 및 단기 수급선(VWAP) 추이 분석")
            chart_data = df[['Close', 'VWAP']]
            chart_data.columns = ['현재가', '수급평균선(VWAP)']
            st.line_chart(chart_data)
            
            st.dataframe(df.tail(5)[['Close', 'Volume', 'VWAP', 'RSI']], use_container_width=True)
    else:
        st.sidebar.warning("⚠️ App Key와 App Secret을 입력해 주세요.")
else:
    st.info("💡 왼쪽 사이드바에 정보를 입력하고 [실시간 시세 갱신] 버튼을 누르면 연동이 시작됩니다.")
