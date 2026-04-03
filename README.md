# NEPSE Smart — Backend API

FastAPI server providing live NEPSE data to nepse.amitacharya.com.np

## Deploy on Render.com (Free)

1. Push this folder to a GitHub repo (e.g. `nepse-smart-api`)
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects render.yaml
5. Click Deploy

Your API will be live at: `https://nepse-smart-api.onrender.com`

## Local Test

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# Visit: http://localhost:8000/api/stocks
```
