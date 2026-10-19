export const config = {
  apiBaseUrl: (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, ""),
  /** "firebase" in deployed envs; "dev" talks to a backend running AUTH_MODE=dev (local only). */
  authMode: (process.env.NEXT_PUBLIC_AUTH_MODE ?? "firebase") as "firebase" | "dev",
  release: process.env.NEXT_PUBLIC_RELEASE ?? "dev",
  firebase: {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
  },
};
