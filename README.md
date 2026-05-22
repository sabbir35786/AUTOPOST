# Auto Poster Agentic AI

This project has a FastAPI backend and a Next.js frontend for generating, scheduling, and publishing Facebook page posts.

## Run Locally

Backend:

```bash
cd backend
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm run dev
```

The backend runs on `http://localhost:8000` and the frontend runs on `http://localhost:3000`.

## Environment

Backend variables live in `backend/.env`:

```env
DATABASE_URL=sqlite:///./test.db
SECRET_KEY=your-super-secret-key-change-me
FACEBOOK_APP_ID=your-facebook-app-id
FACEBOOK_APP_SECRET=your-facebook-app-secret
OPENAI_API_KEY=your-openai-api-key
FRONTEND_URL=http://localhost:3000
```

Frontend variables live in `frontend/.env.local`:

```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_FACEBOOK_APP_ID=your-facebook-app-id
```

Copy the included `.env.example` files before running each app.
