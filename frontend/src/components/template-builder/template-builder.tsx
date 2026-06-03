"use client"

import * as React from "react"
import { Loader2, X } from "lucide-react"
import { toast } from "sonner"

import {
  TemplateDescribeTab,
  type DescribeGenerateResult,
} from "@/components/template-builder/template-describe-tab"
import { TemplateJsonEditor } from "@/components/template-builder/template-json-editor"
import { TemplateOptionBuilder } from "@/components/template-builder/template-option-builder"
import { TemplateVisualBuilder } from "@/components/template-builder/template-visual-builder"
import { useTemplateAssets } from "@/components/template-builder/use-template-assets"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { api, getApiErrorMessage } from "@/lib/api"
import {
  apiTemplateJson,
  applyTemplateJsonToState,
  createInitialTemplateState,
  syncCanvasFieldsFromAspect,
} from "@/lib/template-state"
import type { AspectKey, BuilderTab, ManualTemplateJson, TemplateState } from "@/lib/template-types"
import { ASPECT_PRESETS } from "@/lib/template-types"
import { validateForSave } from "@/lib/template-validation"
import { cn } from "@/lib/utils"

const TABS: { id: BuilderTab; label: string }[] = [
  { id: "visual", label: "Visual Builder" },
  { id: "option", label: "Option Builder" },
  { id: "json", label: "JSON Editor" },
  { id: "describe", label: "Describe It" },
]

type Props = {
  onCancel: () => void
  onSaved: () => void
}

export function TemplateBuilder({ onCancel, onSaved }: Props) {
  const [state, setState] = React.useState<TemplateState>(() => createInitialTemplateState())
  const [activeTab, setActiveTab] = React.useState<BuilderTab>("visual")
  const [jsonValid, setJsonValid] = React.useState(true)
  const [saving, setSaving] = React.useState(false)
  const { backgroundAssets, fontAssets, loading: loadingAssets } = useTemplateAssets()

  function requestTabChange(tab: BuilderTab) {
    if (activeTab === "json" && !jsonValid && tab !== "json") {
      const ok = window.confirm(
        "Your JSON has errors. Fix them before switching tabs or your changes will be lost.",
      )
      if (!ok) return
    }
    setActiveTab(tab)
  }

  function handleJsonValidApply(json: ManualTemplateJson) {
    setState((s) => applyTemplateJsonToState(s, json))
  }

  function handleGenerated(result: DescribeGenerateResult) {
    const aspect = (
      result.aspect_ratio in ASPECT_PRESETS ? result.aspect_ratio : "1:1"
    ) as AspectKey
    setState((s) => {
      const next = applyTemplateJsonToState(s, result.template_json, result.suggested_name)
      return {
        ...next,
        aspectRatio: aspect,
        canvasWidth: result.canvas_width,
        canvasHeight: result.canvas_height,
        previewBackgroundAssetId:
          result.template_json.background_options[0]?.asset_id ?? s.previewBackgroundAssetId,
      }
    })
    setJsonValid(true)
    setActiveTab("visual")
  }

  function handleAspectChange(ratio: AspectKey) {
    setState((s) => syncCanvasFieldsFromAspect(s, ratio))
  }

  async function saveTemplate() {
    const errors = validateForSave(
      { name: state.name, templateJson: apiTemplateJson(state) },
      backgroundAssets,
      fontAssets,
    )
    if (errors.length) {
      toast.error(errors[0].message)
      return
    }
    setSaving(true)
    try {
      const tj = apiTemplateJson(state)
      await api.post("/api/image-templates/manual", {
        name: state.name.trim(),
        canvas_width: tj.canvas_width,
        canvas_height: tj.canvas_height,
        aspect_ratio: tj.aspect_ratio,
        template_json: tj,
      })
      toast.success("Template saved!")
      onSaved()
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Failed to save template."))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="border-purple-200">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2">
          <span>New Template</span>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            <X className="size-4 mr-1" /> Cancel
          </Button>
        </CardTitle>

        <div className="grid sm:grid-cols-[1fr_auto_auto] gap-3 mt-3 max-w-2xl">
          <div className="grid gap-1">
            <Label className="text-xs">Template name</Label>
            <Input
              value={state.name}
              onChange={(e) => setState((s) => ({ ...s, name: e.target.value }))}
              placeholder="e.g. Bold Quote Card"
            />
          </div>
          <div className="grid gap-1">
            <Label className="text-xs">Canvas size</Label>
            <Select
              value={state.aspectRatio}
              onChange={(e) => handleAspectChange(e.target.value as AspectKey)}
            >
              {Object.entries(ASPECT_PRESETS).map(([key, p]) => (
                <option key={key} value={key}>
                  {p.label}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="flex flex-wrap gap-1 mt-4 border-b">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => requestTabChange(tab.id)}
              className={cn(
                "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
                activeTab === tab.id
                  ? "border-purple-600 text-purple-900"
                  : "border-transparent text-slate-500 hover:text-slate-800",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </CardHeader>

      <CardContent className="grid gap-6 min-h-[480px]">
        {activeTab === "visual" ? (
          <TemplateVisualBuilder
            state={state}
            backgrounds={backgroundAssets}
            fonts={fontAssets}
            onStateChange={setState}
            onExportToJson={() => setActiveTab("json")}
          />
        ) : null}

        {activeTab === "option" ? (
          <TemplateOptionBuilder
            state={state}
            backgrounds={backgroundAssets}
            fonts={fontAssets}
            loadingAssets={loadingAssets}
            onStateChange={setState}
          />
        ) : null}

        {activeTab === "json" ? (
          <TemplateJsonEditor
            templateJson={state.templateJson}
            aspectRatio={state.aspectRatio}
            backgrounds={backgroundAssets}
            fonts={fontAssets}
            onValidApply={handleJsonValidApply}
            onValidationChange={setJsonValid}
            onApplyToVisual={() => setActiveTab("visual")}
          />
        ) : null}

        {activeTab === "describe" ? (
          <TemplateDescribeTab
            aspectRatio={state.aspectRatio}
            backgrounds={backgroundAssets}
            loadingAssets={loadingAssets}
            onGenerated={handleGenerated}
          />
        ) : null}

        <div className="flex justify-end border-t pt-4">
          <Button
            type="button"
            className="bg-purple-700 text-white hover:bg-purple-800"
            onClick={saveTemplate}
            disabled={saving}
          >
            {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
            Save Template
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
