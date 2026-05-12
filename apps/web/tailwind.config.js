/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      colors: {
        // IT-Gemak brand. Mostly the 500 shade #128ece; the rest is
        // generated to give Tailwind a full ramp for hover/active/text/bg.
        brand: {
          50: "#e8f3fb",
          100: "#cbe5f7",
          200: "#97caee",
          300: "#5cade2",
          400: "#2f9ad6",
          500: "#128ece",
          600: "#0e74a8",
          700: "#0a5a82",
          800: "#07415e",
          900: "#04293c",
        },
      },
    },
  },
  plugins: [],
};
