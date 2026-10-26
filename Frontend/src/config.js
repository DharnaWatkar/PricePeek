// During Vite dev, talk to the local backend; in a production build the
// frontend is served BY the FastAPI app, so same-origin ("" = relative) URLs.
export const BASE = import.meta.env.DEV ? "http://localhost:8000" : "";
