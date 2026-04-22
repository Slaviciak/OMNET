// Medium-scale OSPF backbone used for dissertation experiments.
//
// The routers and routing behavior come from standard INET components. Optional
// project-local controllers can add controlled synthetic degradation proxies,
// a traffic bottleneck approximation, or the first AI-MRCE runtime prototype
// without modifying OSPF internals.

package dissertationsim.simulations.regionalbackbone;

import dissertationsim.controller.AiMrceController;
import dissertationsim.controller.LinkDegradationController;
import inet.common.misc.ThruputMeteringChannel;
import inet.common.scenario.ScenarioManager;
import inet.networklayer.configurator.ipv4.Ipv4NetworkConfigurator;
import inet.node.inet.StandardHost;
import inet.node.ospfv2.OspfRouter;

network RegionalBackbone
{
    parameters:
        bool enableDegradationController = default(false);
        // Enables the fixed 10 Mbps preferred-span bottleneck used by the
        // traffic-driven congestion approximation branch.
        bool enableCoreBottleneck = default(false);
        // Enables the project-local AI-MRCE runtime prototype. Standard OSPF
        // behavior still comes from the underlying INET routers.
        bool enableAiMrceController = default(false);
        @display("b=1120,520");
    types:
        channel Eth100M extends ThruputMeteringChannel
        {
            delay = 0.1us;
            datarate = 100Mbps;
            thruputDisplayFormat = "#N";
        }
        channel BottleneckEth10M extends ThruputMeteringChannel
        {
            // Simple fixed-capacity bottleneck for the congestion branch.
            delay = 0.1us;
            datarate = 10Mbps;
            thruputDisplayFormat = "#N";
        }
    submodules:
        hostA: StandardHost {
            parameters:
                @display("p=60,260;i=device/laptop");
            gates:
                ethg[1];
        }
        accessA: OspfRouter {
            parameters:
                @display("p=170,260");
            gates:
                ethg[3];
        }
        west1: OspfRouter {
            parameters:
                @display("p=310,160");
            gates:
                ethg[2];
        }
        west2: OspfRouter {
            parameters:
                @display("p=310,360");
            gates:
                ethg[2];
        }
        coreNW: OspfRouter {
            parameters:
                @display("p=470,140");
            gates:
                ethg[4];
        }
        coreNE: OspfRouter {
            parameters:
                @display("p=650,140");
            gates:
                ethg[4];
        }
        coreSW: OspfRouter {
            parameters:
                @display("p=470,380");
            gates:
                ethg[4];
        }
        coreSE: OspfRouter {
            parameters:
                @display("p=650,380");
            gates:
                ethg[4];
        }
        coreC1: OspfRouter {
            parameters:
                @display("p=560,245");
            gates:
                ethg[2];
        }
        coreC2: OspfRouter {
            parameters:
                @display("p=560,275");
            gates:
                ethg[2];
        }
        east1: OspfRouter {
            parameters:
                @display("p=810,160");
            gates:
                ethg[2];
        }
        east2: OspfRouter {
            parameters:
                @display("p=810,360");
            gates:
                ethg[2];
        }
        accessB: OspfRouter {
            parameters:
                @display("p=950,260");
            gates:
                ethg[3];
        }
        hostB: StandardHost {
            parameters:
                @display("p=1060,260;i=device/laptop");
            gates:
                ethg[1];
        }
        configurator: Ipv4NetworkConfigurator {
            parameters:
                config = xml("<config>" +
                             "<interface among='hostA accessA' address='10.10.1.x' netmask='255.255.255.0' />" +
                             "<interface among='accessA west1' address='10.10.11.x' netmask='255.255.255.0' />" +
                             "<interface among='accessA west2' address='10.10.12.x' netmask='255.255.255.0' />" +
                             "<interface among='west1 coreNW' address='10.10.21.x' netmask='255.255.255.0' />" +
                             "<interface among='west2 coreSW' address='10.10.22.x' netmask='255.255.255.0' />" +
                             "<interface among='coreNW coreNE' address='10.10.31.x' netmask='255.255.255.0' />" +
                             "<interface among='coreSW coreSE' address='10.10.32.x' netmask='255.255.255.0' />" +
                             "<interface among='coreNW coreSW' address='10.10.33.x' netmask='255.255.255.0' />" +
                             "<interface among='coreNE coreSE' address='10.10.34.x' netmask='255.255.255.0' />" +
                             "<interface among='coreNW coreC1' address='10.10.41.x' netmask='255.255.255.0' />" +
                             "<interface among='coreC1 coreSE' address='10.10.42.x' netmask='255.255.255.0' />" +
                             "<interface among='coreSW coreC2' address='10.10.43.x' netmask='255.255.255.0' />" +
                             "<interface among='coreC2 coreNE' address='10.10.44.x' netmask='255.255.255.0' />" +
                             "<interface among='coreNE east1' address='10.10.51.x' netmask='255.255.255.0' />" +
                             "<interface among='coreSE east2' address='10.10.52.x' netmask='255.255.255.0' />" +
                             "<interface among='east1 accessB' address='10.10.61.x' netmask='255.255.255.0' />" +
                             "<interface among='east2 accessB' address='10.10.62.x' netmask='255.255.255.0' />" +
                             "<interface among='accessB hostB' address='10.10.2.x' netmask='255.255.255.0' />" +
                             "<route hosts='hostA hostB' destination='*' netmask='0.0.0.0' interface='eth0' />" +
                             "</config>");
                addStaticRoutes = false;
                addDefaultRoutes = false;
                @display("p=60,60;is=s");
        }
        scenarioManager: ScenarioManager {
            @display("p=60,460;is=s");
        }
        degradationController: LinkDegradationController if enableDegradationController {
            @display("p=170,460;is=s");
        }
        aiMrceController: AiMrceController if enableAiMrceController {
            // First runtime AI-MRCE prototype. It observes telemetry and uses
            // administrative withdrawal as its initial protective action.
            @display("p=300,460;is=s");
        }
    connections:
        hostA.ethg[0] <--> Eth100M <--> accessA.ethg[0];
        accessA.ethg[1] <--> Eth100M <--> west1.ethg[0];
        accessA.ethg[2] <--> Eth100M <--> west2.ethg[0];
        west1.ethg[1] <--> Eth100M <--> coreNW.ethg[0];
        west2.ethg[1] <--> Eth100M <--> coreSW.ethg[0];
        coreNW.ethg[1] <--> Eth100M <--> coreNE.ethg[0] if !enableCoreBottleneck;
        coreNW.ethg[1] <--> BottleneckEth10M <--> coreNE.ethg[0] if enableCoreBottleneck;
        coreSW.ethg[1] <--> Eth100M <--> coreSE.ethg[0];
        coreNW.ethg[2] <--> Eth100M <--> coreSW.ethg[2];
        coreNE.ethg[1] <--> Eth100M <--> coreSE.ethg[1];
        coreNW.ethg[3] <--> Eth100M <--> coreC1.ethg[0];
        coreC1.ethg[1] <--> Eth100M <--> coreSE.ethg[2];
        coreSW.ethg[3] <--> Eth100M <--> coreC2.ethg[0];
        coreC2.ethg[1] <--> Eth100M <--> coreNE.ethg[2];
        coreNE.ethg[3] <--> Eth100M <--> east1.ethg[0];
        coreSE.ethg[3] <--> Eth100M <--> east2.ethg[0];
        east1.ethg[1] <--> Eth100M <--> accessB.ethg[0];
        east2.ethg[1] <--> Eth100M <--> accessB.ethg[1];
        accessB.ethg[2] <--> Eth100M <--> hostB.ethg[0];
}
