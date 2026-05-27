import js from "@eslint/js";
import importPlugin from "eslint-plugin-import";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import unusedImportsPlugin from "eslint-plugin-unused-imports";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      ".appdata-test/**",
      ".claude/**",
      ".jupyter-config-test/**",
      ".jupyter-runtime-test/**",
      ".localappdata-test/**",
      ".mypy_cache/**",
      ".pytest_cache/**",
      ".pytest_tmp/**",
      ".pytest_tmp_verify/**",
      ".ruff_cache/**",
      ".selenium-cache/**",
      ".selenium-profile/**",
      ".selenium-venv/**",
      ".userprofile-test/**",
      ".uv-cache/**",
      ".venv/**",
      ".venv_pkgtest/**",
      "dist/**",
      "eslint.config.mjs",
      "jupyter-workspaces-*/**",
      "jupyterlab_core/**",
      "lib/**",
      "node_modules/**",
      "pytest-cache-files-*/**",
      "pytest-temp-root/**",
      "save_my_jupyter/labextension/**",
      "scripts/**",
      "selenium-profile-*/**",
      "test-dist/**",
      "tmp*/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    files: ["src/**/*.{ts,tsx}", "ui_tests/**/*.ts"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        project: ["./tsconfig.json", "./tsconfig.test.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      import: importPlugin,
      react: reactPlugin,
      "react-hooks": reactHooksPlugin,
      "unused-imports": unusedImportsPlugin,
    },
    rules: {
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-unnecessary-type-assertion": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/no-unsafe-return": "error",
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      complexity: "off",
      "import/order": [
        "error",
        {
          alphabetize: { order: "asc", caseInsensitive: true },
          "newlines-between": "always",
        },
      ],
      "react-hooks/exhaustive-deps": "error",
      "react-hooks/rules-of-hooks": "error",
      "unused-imports/no-unused-imports": "error",
    },
    settings: {
      react: {
        version: "detect",
      },
    },
  },
);
