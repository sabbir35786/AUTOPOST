import Link from "next/link"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export default function Home() {
  return (
    <main className="mx-auto flex min-h-[calc(100vh-3.5rem)] w-full max-w-6xl flex-col gap-8 px-4 py-8 md:py-14">
      <section className="grid gap-6 md:grid-cols-[1.2fr_0.8fr] md:items-center">
        <div className="flex flex-col gap-4">
          <h1 className="max-w-2xl text-3xl font-semibold tracking-normal md:text-5xl">
            Plan, generate, and publish Facebook posts from one quiet dashboard.
          </h1>
          <p className="max-w-xl text-base text-muted-foreground md:text-lg">
            Connect your page, set a schedule, and let the backend prepare posts around your niche.
          </p>
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
            <Button asChild className="w-full sm:w-auto">
              <Link href="/register">Create account</Link>
            </Button>
            <Button asChild variant="outline" className="w-full sm:w-auto">
              <Link href="/login">Sign in</Link>
            </Button>
          </div>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Workflow</CardTitle>
            <CardDescription>Everything starts in the dashboard.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm text-muted-foreground">
            <p>1. Connect a Facebook Page.</p>
            <p>2. Choose your niche, posting time, and timezone.</p>
            <p>3. Generate drafts or let the scheduler publish automatically.</p>
          </CardContent>
        </Card>
      </section>
    </main>
  )
}
