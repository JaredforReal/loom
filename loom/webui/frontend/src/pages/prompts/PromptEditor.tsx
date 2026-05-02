import { useEffect, useState } from "react"
import CodeMirror from "@uiw/react-codemirror"
import { markdown } from "@codemirror/lang-markdown"
import { EditorView } from "@codemirror/view"

interface PromptEditorProps {
  value: string
  onChange: (next: string) => void
  readOnly: boolean
}

const customTheme = EditorView.theme({
  "&": {
    height: "100%",
    fontSize: "13px",
    backgroundColor: "transparent",
  },
  ".cm-scroller": {
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  },
  ".cm-content": {
    padding: "12px 0",
  },
  ".cm-gutters": {
    backgroundColor: "transparent",
    border: "none",
    color: "hsl(var(--muted-foreground))",
  },
  ".cm-activeLine": {
    backgroundColor: "hsl(var(--accent) / 0.3)",
  },
  ".cm-activeLineGutter": {
    backgroundColor: "transparent",
  },
})

export function PromptEditor({ value, onChange, readOnly }: PromptEditorProps) {
  const [isDark, setIsDark] = useState(() =>
    document.documentElement.classList.contains("dark") ||
    window.matchMedia("(prefers-color-scheme: dark)").matches,
  )

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const handler = () =>
      setIsDark(
        document.documentElement.classList.contains("dark") || mq.matches,
      )
    mq.addEventListener("change", handler)
    const observer = new MutationObserver(handler)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    })
    return () => {
      mq.removeEventListener("change", handler)
      observer.disconnect()
    }
  }, [])

  return (
    <div className="h-full overflow-auto">
      <CodeMirror
        value={value}
        height="100%"
        theme={isDark ? "dark" : "light"}
        extensions={[markdown(), customTheme, EditorView.lineWrapping]}
        editable={!readOnly}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          indentOnInput: true,
          highlightActiveLine: !readOnly,
          highlightActiveLineGutter: !readOnly,
        }}
        onChange={onChange}
      />
    </div>
  )
}
