import Link from "next/link"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

const steps = [
  "Create a Facebook App at developers.facebook.com.",
  "Add the Facebook Login product.",
  "Set the OAuth redirect URI to /auth/facebook/callback on this platform.",
  "Set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET in backend/.env.",
  "Submit for pages_manage_posts, pages_read_engagement, and pages_show_list.",
]

export default function FacebookSetupGuidePage() {
  return (
    <main className="min-h-screen bg-slate-50 p-6">
      <div className="mx-auto grid max-w-3xl gap-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Facebook OAuth Setup Guide</h1>
            <p className="text-sm text-slate-500">Private platform-owner checklist.</p>
          </div>
          <Button asChild variant="outline"><Link href="/dashboard/settings">Back</Link></Button>
        </div>
        <Card>
          <CardHeader><CardTitle>One-time setup</CardTitle></CardHeader>
          <CardContent className="grid gap-3">
            {steps.map((step, index) => (
              <div key={step} className="flex gap-3 rounded-md border p-3 text-sm">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-blue-700 text-xs font-semibold text-white">{index + 1}</span>
                <p>{step}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
