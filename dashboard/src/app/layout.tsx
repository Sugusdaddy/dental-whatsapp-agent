import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Dental Agent — Panel de control',
  description: 'Recepción virtual con IA para clínicas dentales.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="font-sans antialiased bg-neutral-50 text-neutral-900">{children}</body>
    </html>
  );
}
