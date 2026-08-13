import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { candidatesApi } from '@/lib/api'
import { Callout, Spinner } from '@/components/ui'
import type { UploadResult } from '@/types'

export default function UploadDropzone({
  sessionId,
  maxUploadMb,
  disabled,
  disabledReason,
}: {
  sessionId: string
  maxUploadMb: number
  disabled?: boolean
  disabledReason?: string
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [rejected, setRejected] = useState<UploadResult[]>([])
  const [accepted, setAccepted] = useState(0)

  const upload = useMutation({
    mutationFn: (files: File[]) => candidatesApi.upload(sessionId, files),
    onSuccess: (response) => {
      setAccepted(response.accepted)
      setRejected(response.results.filter((result) => !result.accepted))
      void queryClient.invalidateQueries({ queryKey: ['candidates', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['stats', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
  })

  function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0 || disabled) return
    setAccepted(0)
    setRejected([])
    upload.mutate(Array.from(fileList))
  }

  return (
    <div className="space-y-3">
      <div
        className={`rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
          disabled
            ? 'border-ink-200 bg-ink-50/50'
            : dragging
              ? 'border-brand-500 bg-brand-50'
              : 'border-ink-300 bg-white hover:border-ink-400'
        }`}
        onDragOver={(event) => {
          event.preventDefault()
          if (!disabled) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          handleFiles(event.dataTransfer.files)
        }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.doc,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="sr-only"
          onChange={(event) => {
            handleFiles(event.target.files)
            event.target.value = ''
          }}
        />

        {upload.isPending ? (
          <div className="flex items-center justify-center gap-2 text-sm text-ink-600">
            <Spinner />
            {t('upload.uploading', { count: upload.variables?.length ?? 1 })}
          </div>
        ) : (
          <>
            <button
              type="button"
              className="text-sm font-medium text-ink-900 underline-offset-2 hover:underline disabled:no-underline"
              disabled={disabled}
              onClick={() => inputRef.current?.click()}
            >
              {t('upload.dropzone')}
            </button>
            <p className="mt-1 text-xs text-ink-500">{t('upload.formats', { size: maxUploadMb })}</p>
          </>
        )}
      </div>

      {disabled && disabledReason && <Callout tone="warning">{disabledReason}</Callout>}

      {accepted > 0 && (
        <Callout tone="success">{t('upload.accepted', { count: accepted })}</Callout>
      )}

      {rejected.length > 0 && (
        <Callout tone="danger" title={t('upload.rejected', { count: rejected.length })}>
          <ul className="mt-1 space-y-1">
            {rejected.map((result) => (
              <li key={result.filename} className="text-xs">
                <span className="font-medium">{result.filename}</span> — {result.error}
              </li>
            ))}
          </ul>
        </Callout>
      )}

      {upload.isError && (
        <Callout tone="danger">
          {upload.error instanceof Error ? upload.error.message : t('app.error')}
        </Callout>
      )}
    </div>
  )
}
