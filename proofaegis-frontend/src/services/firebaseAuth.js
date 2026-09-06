import { initializeApp, getApps } from "firebase/app";
import {
  getAuth, setPersistence, browserLocalPersistence, onAuthStateChanged,
  signInWithEmailAndPassword, createUserWithEmailAndPassword, updateProfile,
  signOut, sendPasswordResetEmail,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};
const configured = Boolean(firebaseConfig.apiKey && firebaseConfig.authDomain && firebaseConfig.projectId && firebaseConfig.appId);
let auth;
function getFirebaseAuth() {
  if (!configured) throw new Error("Firebase Authentication is not configured.");
  if (!auth) auth = getAuth(getApps().length ? getApps()[0] : initializeApp(firebaseConfig));
  return auth;
}
export const isFirebaseConfigured = () => configured;
export const initializeFirebaseAuth = () => setPersistence(getFirebaseAuth(), browserLocalPersistence);
export const firebaseSignIn = (email, password) => signInWithEmailAndPassword(getFirebaseAuth(), email, password).then(({ user }) => user);
export async function firebaseSignUp(name, email, password) {
  const { user } = await createUserWithEmailAndPassword(getFirebaseAuth(), email, password);
  if (name.trim()) await updateProfile(user, { displayName: name.trim() });
  return user;
}
export const firebaseSignOut = () => signOut(getFirebaseAuth());
export const onFirebaseAuthChanged = (callback) => onAuthStateChanged(getFirebaseAuth(), callback);
export const sendResetEmail = (email) => sendPasswordResetEmail(getFirebaseAuth(), email);
export async function getCurrentIdToken() { return getFirebaseAuth().currentUser?.getIdToken() || null; }
export function toAppUser(user) {
  return user ? { email: user.email, name: user.displayName || user.email, uid: user.uid, workspace: "ProofAegis workspace" } : null;
}
