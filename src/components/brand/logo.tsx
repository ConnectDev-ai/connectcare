import Image from "next/image";
import blackLogo from "@/img/Logo Connect Care Black.png";

export function ConnectCareLogo({ className = "" }: { className?: string }) {
  return (
    <Image
      src={blackLogo}
      alt="Connect Care"
      className={`h-14 w-auto ${className}`}
      priority
    />
  );
}
