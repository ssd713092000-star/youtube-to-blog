"use client";

/**
 * Auth behind a small interface so the provider can be swapped.
 * - firebase: Firebase Auth (Identity Platform): Google popup + passwordless email link.
 * - dev: local-only; sends "Bearer dev:<email>" to a backend running AUTH_MODE=dev.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Auth, User as FirebaseUser } from "firebase/auth";

import { config } from "@/lib/config";
import { logger } from "@/lib/logger";

export interface SessionUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
}

interface AuthApi {
  user: SessionUser | null;
  loading: boolean;
  getToken: (forceRefresh?: boolean) => Promise<string | null>;
  signInWithGoogle: () => Promise<void>;
  sendEmailLink: (email: string) => Promise<void>;
  completeEmailLink: () => Promise<boolean>;
  signInDev: (email: string) => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthApi | null>(null);
const DEV_KEY = "t2d_dev_email";
const EMAIL_KEY = "t2d_email_for_signin";

let authPromise: Promise<Auth> | null = null;
function firebaseAuth(): Promise<Auth> {
  authPromise ??= (async () => {
    const { initializeApp, getApps } = await import("firebase/app");
    const { getAuth } = await import("firebase/auth");
    const app = getApps()[0] ?? initializeApp(config.firebase);
    return getAuth(app);
  })();
  return authPromise;
}

function toSession(u: FirebaseUser): SessionUser {
  return { uid: u.uid, email: u.email, displayName: u.displayName, photoURL: u.photoURL };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (config.authMode === "dev") {
      const email = localStorage.getItem(DEV_KEY);
      setUser(email ? { uid: `dev-${email}`, email, displayName: email.split("@")[0] ?? email, photoURL: null } : null);
      setLoading(false);
      return;
    }
    let unsub = () => {};
    void firebaseAuth().then(async (auth) => {
      const { onIdTokenChanged } = await import("firebase/auth");
      unsub = onIdTokenChanged(auth, (u) => {
        setUser(u ? toSession(u) : null);
        setLoading(false);
      });
    });
    return () => unsub();
  }, []);

  const getToken = useCallback(async (forceRefresh = false) => {
    if (config.authMode === "dev") {
      const email = localStorage.getItem(DEV_KEY);
      return email ? `dev:${email}` : null;
    }
    const auth = await firebaseAuth();
    return auth.currentUser ? auth.currentUser.getIdToken(forceRefresh) : null;
  }, []);

  const signInWithGoogle = useCallback(async () => {
    const auth = await firebaseAuth();
    const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
    await signInWithPopup(auth, new GoogleAuthProvider());
    logger.info("signed in", { method: "google" });
  }, []);

  const sendEmailLink = useCallback(async (email: string) => {
    const auth = await firebaseAuth();
    const { sendSignInLinkToEmail } = await import("firebase/auth");
    await sendSignInLinkToEmail(auth, email, { url: `${window.location.origin}/login`, handleCodeInApp: true });
    localStorage.setItem(EMAIL_KEY, email);
  }, []);

  const completeEmailLink = useCallback(async () => {
    if (config.authMode === "dev") return false;
    const auth = await firebaseAuth();
    const { isSignInWithEmailLink, signInWithEmailLink } = await import("firebase/auth");
    if (!isSignInWithEmailLink(auth, window.location.href)) return false;
    const email = localStorage.getItem(EMAIL_KEY) ?? window.prompt("Confirm your email") ?? "";
    await signInWithEmailLink(auth, email, window.location.href);
    localStorage.removeItem(EMAIL_KEY);
    logger.info("signed in", { method: "email_link" });
    return true;
  }, []);

  const signInDev = useCallback((email: string) => {
    localStorage.setItem(DEV_KEY, email);
    setUser({ uid: `dev-${email}`, email, displayName: email.split("@")[0] ?? email, photoURL: null });
  }, []);

  const signOut = useCallback(async () => {
    if (config.authMode === "dev") {
      localStorage.removeItem(DEV_KEY);
      setUser(null);
      return;
    }
    const auth = await firebaseAuth();
    const { signOut: fbSignOut } = await import("firebase/auth");
    await fbSignOut(auth);
  }, []);

  const value = useMemo<AuthApi>(
    () => ({ user, loading, getToken, signInWithGoogle, sendEmailLink, completeEmailLink, signInDev, signOut }),
    [user, loading, getToken, signInWithGoogle, sendEmailLink, completeEmailLink, signInDev, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Token getter usable outside React (API client). Set by <Providers>. */
export const tokenSource: { get: (force?: boolean) => Promise<string | null>; onUnauthorized: () => void } = {
  get: async () => null,
  onUnauthorized: () => {},
};
