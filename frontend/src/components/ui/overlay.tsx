"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as SliderPrimitive from "@radix-ui/react-slider";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- Dialog / Sheet
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  title,
  description,
  children,
  className,
  side,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  side?: "right";
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px]" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 border border-border bg-surface shadow-xl focus:outline-none",
          side === "right"
            ? "inset-y-0 right-0 flex w-full max-w-2xl flex-col"
            : "left-1/2 top-1/2 max-h-[90vh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <DialogPrimitive.Title className="text-sm font-semibold text-fg">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-1 text-xs text-fg-subtle">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{String(title)}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close className="rounded p-1 text-fg-subtle hover:bg-sidebar" aria-label="Close">
            <X className="h-4 w-4" />
          </DialogPrimitive.Close>
        </div>
        <div className={cn("px-5 py-4", side === "right" && "flex-1 overflow-y-auto")}>{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

// ---------------------------------------------------------------- Tabs
export const Tabs = TabsPrimitive.Root;
export function TabsList({ className, ...props }: TabsPrimitive.TabsListProps) {
  return <TabsPrimitive.List className={cn("inline-flex items-center gap-1 rounded-lg bg-sidebar p-1", className)} {...props} />;
}
export function TabsTrigger({ className, ...props }: TabsPrimitive.TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "rounded-md px-3 py-1 text-xs font-medium text-fg-subtle transition-colors",
        "data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm",
        className,
      )}
      {...props}
    />
  );
}
export const TabsContent = TabsPrimitive.Content;

// ---------------------------------------------------------------- Tooltip
export const TooltipProvider = TooltipPrimitive.Provider;
export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  if (!content) return <>{children}</>;
  return (
    <TooltipPrimitive.Root delayDuration={200}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-fg px-2.5 py-1.5 text-xs text-bg shadow-lg"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

// ---------------------------------------------------------------- Popover
export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export function PopoverContent({ className, ...props }: PopoverPrimitive.PopoverContentProps) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        sideOffset={6}
        align="start"
        className={cn("z-50 rounded-[10px] border border-border bg-surface shadow-xl focus:outline-none", className)}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}

// ---------------------------------------------------------------- Dropdown
export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownTrigger = DropdownPrimitive.Trigger;
export function DropdownContent({ className, ...props }: DropdownPrimitive.DropdownMenuContentProps) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        sideOffset={6}
        align="end"
        className={cn("z-50 min-w-44 rounded-lg border border-border bg-surface p-1 shadow-xl", className)}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}
export function DropdownItem({ className, danger, ...props }: DropdownPrimitive.DropdownMenuItemProps & { danger?: boolean }) {
  return (
    <DropdownPrimitive.Item
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-sm outline-none select-none",
        "data-[highlighted]:bg-sidebar data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        danger ? "text-danger" : "text-fg",
        className,
      )}
      {...props}
    />
  );
}
export const DropdownSeparator = () => <DropdownPrimitive.Separator className="my-1 h-px bg-border" />;

// ---------------------------------------------------------------- Switch / Slider
export function Switch(props: SwitchPrimitive.SwitchProps) {
  return (
    <SwitchPrimitive.Root
      className="relative h-5 w-9 shrink-0 rounded-full bg-border-strong transition-colors data-[state=checked]:bg-accent"
      {...props}
    >
      <SwitchPrimitive.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </SwitchPrimitive.Root>
  );
}

export function Slider(props: SliderPrimitive.SliderProps & { label: string }) {
  const { label, ...rest } = props;
  return (
    <SliderPrimitive.Root className="relative flex h-5 w-full touch-none items-center select-none" {...rest}>
      <SliderPrimitive.Track className="relative h-1 grow rounded-full bg-border">
        <SliderPrimitive.Range className="absolute h-full rounded-full bg-accent" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        aria-label={label}
        className="block h-4 w-4 rounded-full border-2 border-accent bg-surface shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      />
    </SliderPrimitive.Root>
  );
}
