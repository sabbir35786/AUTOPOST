"use client"

import * as React from "react"
import { Download, Loader2, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { BackgroundAsset, FontAsset, ManualTemplateJson } from "@/lib/template-types"
import { templateJsonSkeletonString } from "@/lib/template-state"
import { parseJsonString, validateTemplateJson, type ValidationError } from "@/lib/template-validation"
import { cn } from "@/lib/utils"

type JsonEditorMode = "paste" | "upload"

type Props = {
  templateJson: ManualTemplateJson
  aspectRatio: keyof typeof import("@/lib/template-types").ASPECT_PRESETS
  backgrounds: BackgroundAsset[]
  fonts: FontAsset[]
  onValidApply: (json: ManualTemplateJson) => void
  onValidationChange: (valid: boolean) => void
  onApplyToVisual?: () => void
}

export function TemplateJsonEditor({
  templateJson,
  aspectRatio,
  backgrounds,
  fonts,
  onValidApply,
  onValidationChange,
  onApplyToVisual,
}: Props) {
  const [mode, setMode] = React.useState<JsonEditorMode>("paste")
  const [text, setText] = React.useState(() => JSON.stringify(templateJson, null, 2))
  const [errors, setErrors] = React.useState<ValidationError[]>([])
  const [parseError, setParseError] = React.useState<string | null>(null)
  const fileRef = React.useRef<HTMLInputElement>(null)
  const debounceRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  React.useEffect(() => {
    setText(JSON.stringify(templateJson, null, 2))
  }, [templateJson])

  const runValidation = React.useCallback(
    (value: string) => {
      const { data, parseError: pe } = parseJsonString(value)
      setParseError(pe)
      if (pe) {
        setErrors([])
        onValidationChange(false)
        return
      }
      const result = validateTemplateJson(data, backgrounds, fonts)
      setErrors(result.errors)
      onValidationChange(result.valid)
      if (result.valid && result.json) {
        onValidApply(result.json)
      }
    },
    [backgrounds, fonts, onValidApply, onValidationChange],
  )

  React.useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runValidation(text), 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [text, runValidation])

  function formatJson() {
    const { data, parseError: pe } = parseJsonString(text)
    if (pe || !data) return
    setText(JSON.stringify(data, null, 2))
  }

  function loadSkeleton() {
    setText(templateJsonSkeletonString(aspectRatio))
  }

  function downloadJson() {
    const blob = new Blob([text], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "template.json"
    a.click()
    URL.revokeObjectURL(url)
  }

  function handleFileUpload(file: File) {
    const reader = new FileReader()
    reader.onload = () => {
      const content = String(reader.result ?? "")
      setText(content)
      setMode("paste")
    }
    reader.readAsText(file)
  }

  const lines = text.split("\n")
  const errorPaths = new Set(errors.map((e) => e.path))

  return (
    <div className="grid gap-3 h-full min-h-[420px]">
      <div className="flex flex-wrap gap-2 items-center">
        <div className="flex rounded-md border overflow-hidden">
          <button
            type="button"
            className={cn(
              "px-3 py-1.5 text-sm",
              mode === "paste" && "bg-purple-100 text-purple-900 font-medium",
            )}
            onClick={() => setMode("paste")}
          >
            Paste JSON
          </button>
          <button
            type="button"
            className={cn(
              "px-3 py-1.5 text-sm border-l",
              mode === "upload" && "bg-purple-100 text-purple-900 font-medium",
            )}
            onClick={() => setMode("upload")}
          >
            Upload File
          </button>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={formatJson}>
          Format JSON
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => runValidation(text)}>
          Validate
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={loadSkeleton}>
          Load skeleton
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={downloadJson}>
          <Download className="size-4 mr-1" /> Download JSON
        </Button>
        {onApplyToVisual ? (
          <Button
            type="button"
            size="sm"
            className="bg-purple-700 text-white hover:bg-purple-800"
            disabled={!!parseError || errors.length > 0}
            onClick={() => {
              const { data } = parseJsonString(text)
              if (!data) return
              const result = validateTemplateJson(data, backgrounds, fonts)
              if (result.valid && result.json) {
                onValidApply(result.json)
                onApplyToVisual()
              }
            }}
          >
            Apply to Visual Builder
          </Button>
        ) : null}
      </div>

      {mode === "upload" ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleFileUpload(f)
            }}
          />
          <Upload className="size-8 mx-auto text-slate-400 mb-2" />
          <p className="text-sm text-slate-600 mb-3">Upload a .json template file</p>
          <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}>
            Choose file
          </Button>
        </div>
      ) : null}

      <div className={cn("flex flex-1 min-h-[360px] rounded-lg border overflow-hidden", mode === "upload" && "hidden")}>
        <div
          className="shrink-0 bg-slate-100 text-slate-500 text-xs font-mono py-3 px-2 select-none overflow-hidden"
          aria-hidden
        >
          {lines.map((_, i) => (
            <div key={i} className="leading-5 text-right pr-1">
              {i + 1}
            </div>
          ))}
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          className={cn(
            "flex-1 font-mono text-sm p-3 resize-none outline-none leading-5",
            (parseError || errors.length > 0) && "bg-red-50/30",
          )}
          style={{ tabSize: 2 }}
        />
      </div>

      {parseError ? (
        <p className="text-sm text-red-600">Parse error: {parseError}</p>
      ) : null}
      {errors.length > 0 ? (
        <ul className="text-sm text-red-600 list-disc pl-5 space-y-1 max-h-32 overflow-auto">
          {errors.map((e, i) => (
            <li key={i}>
              {e.path ? `${e.path}: ` : ""}
              {e.message}
            </li>
          ))}
        </ul>
      ) : errors.length === 0 && !parseError && text.trim() ? (
        <p className="text-sm text-green-700">JSON is valid.</p>
      ) : null}
      {errorPaths.size > 0 ? null : null}
    </div>
  )
}
