package dev.integratepbr;

import com.mojang.logging.LogUtils;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.neoforge.client.event.RegisterClientReloadListenersEvent;
import net.neoforged.fml.ModList;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.fml.event.lifecycle.FMLClientSetupEvent;
import net.neoforged.neoforge.common.NeoForge;
import org.slf4j.Logger;

import java.util.stream.Collectors;

@EventBusSubscriber(modid = IntegratePbr.MOD_ID, value = Dist.CLIENT)
public final class IntegratePbrClient {
    private static final Logger LOGGER = LogUtils.getLogger();

    private IntegratePbrClient() {
    }

    @SubscribeEvent
    public static void onReloadListeners(RegisterClientReloadListenersEvent event) {
        event.registerReloadListener((barrier, resources, prepareProfiler, reloadProfiler, background, game) ->
                java.util.concurrent.CompletableFuture.runAsync(() -> GeneratedPackManager.update(resources), background)
                        .thenCompose(barrier::wait));
    }

    @SubscribeEvent
    public static void onClientSetup(FMLClientSetupEvent event) {
        NeoForge.EVENT_BUS.addListener(MaterialCommands::register);
        NeoForge.EVENT_BUS.addListener(GeneratedPackManager::onClientTick);
        String modIds = ModList.get().getMods().stream()
                .map(mod -> mod.getModId())
                .filter(id -> !id.equals(IntegratePbr.MOD_ID))
                .sorted()
                .collect(Collectors.joining(", "));
        LOGGER.info("Integrate PBR detected mods: {}", modIds);
    }
}
