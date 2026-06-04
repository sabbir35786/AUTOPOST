"use client"

import * as React from "react"
import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type SheetContextValue = {
  open: boolean
  setOpen: (open: boolean) => void
}

const SheetContext = React.createContext<SheetContextValue | null>(null)

function useSheet() {
  const context = React.useContext(SheetContext)
  if (!context) {
    throw new Error("Sheet components must be used inside Sheet")
  }
  return context
}

function Sheet({
  children,
  open,
  onOpenChange,
}: {
  children: React.ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const [internalOpen, setInternalOpen] = React.useState(false)
  const currentOpen = open ?? internalOpen
  const setOpen = onOpenChange ?? setInternalOpen

  return (
    <SheetContext.Provider value={{ open: currentOpen, setOpen }}>
      {children}
    </SheetContext.Provider>
  )
}

function SheetTrigger({
  children,
  asChild,
}: {
  children: React.ReactElement
  asChild?: boolean
}) {
  const { setOpen } = useSheet()
  if (asChild) {
    return React.cloneElement(children, {
      onClick: (event: React.MouseEvent) => {
        children.props.onClick?.(event)
        setOpen(true)
      },
    })
  }
  return <button onClick={() => setOpen(true)}>{children}</button>
}

function SheetContent({
  children,
  className,
}: React.ComponentProps<"div">) {
  const { open, setOpen } = useSheet()

  if (!open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50">
      <button
        aria-label="Close navigation"
        className="absolute inset-0 bg-foreground/20"
        onClick={() => setOpen(false)}
      />
      <div
        className={cn(
          "absolute right-0 top-0 flex h-full w-80 max-w-[85vw] flex-col border-l bg-background p-4 shadow-lg",
          className
        )}
      >
        <div className="mb-4 flex justify-end">
          <Button
            aria-label="Close menu"
            size="icon"
            variant="ghost"
            onClick={() => setOpen(false)}
          >
            <X className="size-4" />
          </Button>
        </div>
        {children}
      </div>
    </div>
  )
}

export { Sheet, SheetContent, SheetTrigger }
