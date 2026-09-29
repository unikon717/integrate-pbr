package dev.integratepbr;

import net.neoforged.bus.api.IEventBus;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.fml.common.Mod;

@Mod(value = IntegratePbr.MOD_ID, dist = Dist.CLIENT)
public final class IntegratePbr {
    public static final String MOD_ID = "integratepbr";

    public IntegratePbr(IEventBus modEventBus) {
        // Client-only setup lives in IntegratePbrClient.
    }
}
