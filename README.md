# Flower Collaborative Agent Hackathon
This demo is a proof of concept demonstrating communication from smart buildings to a smart city. We created two buildings with different profiles in terms of height and occupancy.
We then generated two different datasets, one for each building, containing time stamped measurements of occupancy, electricity and gas consuption, as well as water consumption. The datasets cover one year of operation with one minute granulometry.
This demo runs a Flower Collaborative Agent across two SuperNodes. Each SuperNode has its own synthetic building records in `data/`for the agent to work with. This example uses [@flwrlabs/collaborative-agent](https://flower.ai/apps/flwrlabs/collaborative-agent).

> [!NOTE]
> To follow along, you'll need a [Flower account](https://flower.ai) with access to SuperGrid.

## Federation setup

![Map of the two buildings in San Francisco(mapbuildings.png)

| Example site | SuperNode | Patient records |
| --- | --- | --- |
| Building A: Solaire | `supernode-1` | [Data CSV](data/supernode-building-a/Building%20A%20solaire%20description.xlsx) |
| Building B: Sales force Tower | `supernode-2` | [Data CSV](data/supernode-building-b/Building%20B%20Sales%20force%20Tower%20description.xlsx) |


### Register and connect SuperNodes to SuperGrid

#### Create keys

Create a public-private key pair for each SuperNode:

```shell
mkdir keys
for i in {0..1}; do
  ssh-keygen -t ecdsa -b 384 -N "" -C "supernode-$i" -f "keys/supernode-$i"
done
```

#### Register SuperNodes

Log in to SuperGrid on the machine you'll use to register the SuperNodes:

```shell
uvx flwr login supergrid
```

Register each SuperNode with its public key. The example names and locations will appear on the federation map.

```bash
uvx flwr supernode register keys/supernode-0.pub supergrid --name="Building A: Solaire, 299 Fremont st, SFr" --location="-37.788241,-22.393614"

uvx flwr supernode register keys/supernode-1.pub supergrid --name="Building B: Salesforce Tower, 415 Mission st, SF" --location="-37.789774,-122.396932"


```

### Launch your SuperNodes

From the repository root, set your model API key and start the four SuperNodes. The Compose file mounts the matching `data/` directory into each container.

> [!TIP]
> You can get your API KEY from flower.ai navigating to `Profile -> Settings -> API Keys`

```shell
export FLWR_MODEL_API_KEY="your-key"
docker compose up
```

To stop them, press Ctrl+C, then remove the containers:

```shell
docker compose down
```

### Create a federation and add SuperNodes

To use the SuperNodes together, add them to a _federation_. A federation groups its members and SuperNodes; a SuperNode can belong to multiple federations.

Create the federation and add the SuperNodes with the Flower CLI or on [flower.ai](https://flower.ai). Follow these guides:

- [Create and Manage Federations](https://flower.ai/docs/framework/how-to-create-and-manage-federations.html). Ensure you create a federation of type `deployment`, this ensures `SuperNodes` can be connected to it.
- [Add SuperNodes to a Federation](https://flower.ai/docs/framework/how-to-connect-supernodes-to-supergrid.html)

#### Add the SuperNodes to the `@alaind/smart-legos` federation

This demo uses the `deployment` federation `@alaind/smart-legos`. If it doesn't exist yet, the `alaind` account can create it (federations are deployment type unless `--simulation` is passed):

```shell
uvx flwr federation create smart-legos supergrid --description "Smart buildings to smart city demo"
```

Look up the IDs of your registered SuperNodes:

```shell
uvx flwr supernode list supergrid --verbose
```

Add each SuperNode to the federation, replacing `<supernode-id>` with the IDs from the list:

```shell
uvx flwr federation add-supernode <supernode-id> @alaind/smart-legos supergrid
```

Check that the SuperNodes are in the federation:

```shell
uvx flwr federation list supergrid --federation @alaind/smart-legos
```

## Run the app

Check how to run this app in the [`Flower Chat terminal`](https://flower.ai/docs/agent/tutorials/get-started-with-flower-agent.html) or on [flower.ai](https://flower.ai/docs/agent/tutorials/quickstart.html). For everything else check the [Flower Agent Documentation](https://flower.ai/docs/agent/)
