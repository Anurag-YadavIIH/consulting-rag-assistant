/**
 * Client-side checks for a chosen or dropped file, the same for both paths.
 * They only give fast, friendly feedback: the server enforces the real
 * limits (type, MAX_UPLOAD_MB, MAX_UPLOAD_CHUNKS) on every upload.
 */
import { UPLOAD_ACCEPT } from "./api";

export const UPLOAD_EXTENSIONS = UPLOAD_ACCEPT.split(",");
/** Mirrors the API's default MAX_UPLOAD_MB (25). */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

export interface FileLike {
  name: string;
  size: number;
}

/** Returns an error message, or null if the file looks acceptable. */
export function checkUploadFile(file: FileLike): string | null {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!UPLOAD_EXTENSIONS.includes(ext)) {
    return `Unsupported file type${ext ? ` (${ext})` : ""}. Use ${UPLOAD_EXTENSIONS.join(", ")}.`;
  }
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return "That file is larger than the 25 MB upload limit.";
  return null;
}

/** Picks the single dropped file, applying the same checks. */
export function pickDroppedFile<T extends FileLike>(files: ArrayLike<T> | null | undefined): {
  file: T | null;
  error: string | null;
} {
  if (!files || files.length === 0) return { file: null, error: null };
  if (files.length > 1) return { file: null, error: "Drop one file at a time." };
  const file = files[0];
  const error = checkUploadFile(file);
  return error ? { file: null, error } : { file, error: null };
}
