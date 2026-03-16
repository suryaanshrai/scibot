import { AlertCircle } from 'lucide-react'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import type { HITLPayload } from '@/types/chat'

interface HITLDialogProps {
  payload: HITLPayload | null
  onApprove: () => void
  onDeny: () => void
}

export function HITLDialog({ payload, onApprove, onDeny }: HITLDialogProps) {
  const headline = payload?.question ?? payload?.description ?? 'Approve this action?'
  const details = payload?.details ?? (payload?.args ? JSON.stringify(payload.args, null, 2) : undefined)

  return (
    <AlertDialog open={!!payload}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <AlertCircle className="text-yellow-500" size={18} />
            Agent wants to take an action
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-2">
            <p className="font-medium text-foreground">{headline}</p>
            {payload?.tool && <p className="text-xs text-muted-foreground">Tool: {payload.tool}</p>}
            {details && (
              <pre className="bg-muted rounded p-2 text-xs overflow-auto max-h-40 whitespace-pre-wrap">
                {details}
              </pre>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onDeny}>Deny</AlertDialogCancel>
          <AlertDialogAction onClick={onApprove}>Approve</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
