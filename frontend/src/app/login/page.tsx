// frontend/src/app/login/page.tsx
//
// Form de login (D78). Mensaje de error genérico (el backend no distingue
// email inexistente de contraseña incorrecta). Al éxito, redirige a la
// ruta `redirect` (si vino en el query) o a /admin.
//
// `useSearchParams()` obliga a envolver el componente en un <Suspense> para
// que Next.js 16 pueda prerenderizar la página en build. El default export
// es un wrapper delgado con el Suspense; la lógica real vive en LoginForm.

"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { LogIn } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, isAuthenticated, isLoading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const redirectTo = searchParams.get("redirect") ?? "/admin";

  // Redirigir si ya hay sesión. Va en un useEffect (no en el render):
  // llamar `router.replace()` durante el render dispara el warning
  // "Cannot update a component (Router) while rendering a different
  // component (LoginPage)".
  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated && !isSubmitting) {
      router.replace(redirectTo);
    }
  }, [isLoading, isAuthenticated, isSubmitting, redirectTo, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      // La redirección la maneja el useEffect de arriba cuando
      // `isAuthenticated` pasa a true. No hace falta llamar a
      // router.replace acá.
    } catch (err) {
      setError(err);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-lg">Iniciar sesión</CardTitle>
          <CardDescription>
            Acceso restringido al panel de administración.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={isSubmitting}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Contraseña</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isSubmitting}
              />
            </div>
            {error !== null && (
              <ErrorState error={error} title="No se pudo iniciar sesión" />
            )}
            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting || !email || !password}
            >
              <LogIn className="size-4" />
              {isSubmitting ? "Entrando..." : "Entrar"}
            </Button>
          </form>
          <p className="text-center text-xs text-muted-foreground">
            <Link href="/" className="hover:underline">
              Volver al dashboard
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}

function LoginLoading() {
  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm space-y-4">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginLoading />}>
      <LoginForm />
    </Suspense>
  );
}