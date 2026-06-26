// Shared formatting helpers, color palette, and utilities

export const LABEL_COLORS = {
  File:         { bg: "bg-blue-600",   text: "text-blue-600",   cy: "#3b82f6" },
  Module:       { bg: "bg-blue-400",   text: "text-blue-400",   cy: "#60a5fa" },
  Class:        { bg: "bg-purple-600", text: "text-purple-600", cy: "#9333ea" },
  Interface:    { bg: "bg-purple-400", text: "text-purple-400", cy: "#c084fc" },
  TypeAlias:    { bg: "bg-pink-500",   text: "text-pink-500",   cy: "#ec4899" },
  Function:     { bg: "bg-green-600",  text: "text-green-600",  cy: "#16a34a" },
  Method:       { bg: "bg-green-400",  text: "text-green-400",  cy: "#4ade80" },
  Field:        { bg: "bg-yellow-500", text: "text-yellow-500", cy: "#eab308" },
  Variable:     { bg: "bg-orange-500", text: "text-orange-500", cy: "#f97316" },
  Import:       { bg: "bg-cyan-500",   text: "text-cyan-500",   cy: "#06b6d4" },
  Chunk:        { bg: "bg-gray-500",   text: "text-gray-500",   cy: "#6b7280" },
  GlossaryEntry:{ bg: "bg-rose-600",   text: "text-rose-600",   cy: "#e11d48" },
};

export const LANG_COLORS = {
  typescript: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  javascript: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  tsx:        "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
};

export function labelColor(label) {
  return LABEL_COLORS[label] || { bg: "bg-gray-400", text: "text-gray-400", cy: "#9ca3af" };
}

export function langBadge(lang) {
  return LANG_COLORS[lang] || "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200";
}

export function locationStr(result) {
  const { file_path, start_line, end_line } = result;
  if (!file_path) return "unknown";
  const base = file_path.split("/").slice(-2).join("/");
  return start_line ? `${base}:${start_line}-${end_line}` : base;
}

export function symbolStr(result) {
  return result.function_name || result.class_name || "";
}

export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
