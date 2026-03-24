package dissertationsim.simulations.dualpathbaseline;

import inet.common.misc.ThruputMeteringChannel;
import inet.networklayer.configurator.ipv4.Ipv4NetworkConfigurator;
import inet.node.inet.StandardHost;
import inet.node.ospfv2.OspfRouter;

network DualPathBaseline
{
    parameters:
        @display("b=860,240");
    types:
        channel Eth100M extends ThruputMeteringChannel
        {
            delay = 0.1us;
            datarate = 100Mbps;
            thruputDisplayFormat = "#N";
        }
    submodules:
        hostA: StandardHost {
            parameters:
                @display("p=80,120;i=device/laptop");
            gates:
                ethg[1];
        }
        r1: OspfRouter {
            parameters:
                @display("p=220,120");
            gates:
                ethg[3];
        }
        r2: OspfRouter {
            parameters:
                @display("p=400,70");
            gates:
                ethg[2];
        }
        r4: OspfRouter {
            parameters:
                @display("p=400,170");
            gates:
                ethg[2];
        }
        r3: OspfRouter {
            parameters:
                @display("p=590,120");
            gates:
                ethg[3];
        }
        hostB: StandardHost {
            parameters:
                @display("p=760,120;i=device/laptop");
            gates:
                ethg[1];
        }
        configurator: Ipv4NetworkConfigurator {
            parameters:
                config = xml("<config>" +
                             "<interface among='hostA r1' address='10.0.1.x' netmask='255.255.255.0' />" +
                             "<interface among='r1 r2' address='10.0.12.x' netmask='255.255.255.0' />" +
                             "<interface among='r2 r3' address='10.0.23.x' netmask='255.255.255.0' />" +
                             "<interface among='r1 r4' address='10.0.14.x' netmask='255.255.255.0' />" +
                             "<interface among='r4 r3' address='10.0.43.x' netmask='255.255.255.0' />" +
                             "<interface among='r3 hostB' address='10.0.3.x' netmask='255.255.255.0' />" +
                             "<route hosts='hostA hostB' destination='*' netmask='0.0.0.0' interface='eth0' />" +
                             "</config>");
                addStaticRoutes = false;
                addDefaultRoutes = false;
                @display("p=80,40;is=s");
        }
    connections:
        hostA.ethg[0] <--> Eth100M <--> r1.ethg[0];
        r1.ethg[1] <--> Eth100M <--> r2.ethg[0];
        r2.ethg[1] <--> Eth100M <--> r3.ethg[0];
        r1.ethg[2] <--> Eth100M <--> r4.ethg[0];
        r4.ethg[1] <--> Eth100M <--> r3.ethg[1];
        r3.ethg[2] <--> Eth100M <--> hostB.ethg[0];
}
