import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Identity } from "../api/types";

export function useIdentity() {
  const [me, setMe] = useState<Identity | null | undefined>(undefined);

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  const identify = async (nickname: string) => {
    const id = await api.identify(nickname);
    setMe(id);
    return id;
  };

  return { me, identify, loading: me === undefined };
}
