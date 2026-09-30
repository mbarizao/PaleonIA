"use client";

import { MoonOutlined, SunOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useSyncExternalStore } from "react";
import type { ThemeMode } from "./theme";

const STORAGE_KEY = "paleonia.theme";
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function themeMode(): ThemeMode {
  if (typeof document === "undefined") return "light";
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function subscribeTheme(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function toggleTheme() {
  const next: ThemeMode = themeMode() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem(STORAGE_KEY, next);
  emit();
}

export function useThemeMode() {
  return useSyncExternalStore(subscribeTheme, themeMode, () => "light" as ThemeMode);
}

export function ThemeToggle() {
  const dark = useThemeMode() === "dark";
  return (
    <Button
      className="theme-toggle"
      type="text"
      icon={dark ? <SunOutlined /> : <MoonOutlined />}
      aria-label={dark ? "Usar tema claro" : "Usar tema escuro"}
      onClick={toggleTheme}
    />
  );
}
